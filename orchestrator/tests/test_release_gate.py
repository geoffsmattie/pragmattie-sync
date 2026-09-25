from datetime import datetime

import pytest
from sqlalchemy import select

from sdlc.agents.release_gate import (
    OpenIncident,
    ReleaseFacts,
    evaluate,
    release_tier,
)
from sdlc.tables import AgentDecision, Deployment, Incident, Issue, PullRequest
from sdlc.tiers import load_policy
from tests.fakes import FakeGitHub

POLICY = load_policy()
CI_JOBS = [
    "API (lint + tests)",
    "API (migrations on MySQL)",
    "Web (tests + build)",
    "Orchestrator (lint + tests)",
]


def facts(**kw):
    return ReleaseFacts(**{"tier": "T2", "prs": (7,), "modules": ("pipeline",), **kw})


# --- the rules ---------------------------------------------------------------------------------


def test_low_tiers_deploy_automatically_even_with_an_incident_open():
    incident = (OpenIncident("pipeline", 61),)
    for tier in ("T0", "T1"):
        v = evaluate(POLICY, facts(tier=tier, open_incidents=incident), mode="enforce")
        assert (v.verdict, v.state, v.environment) == ("release", "success", "production")
        assert v.description == f"{tier} · Release: deploys automatically"


def test_t2_passes_its_checks():
    v = evaluate(POLICY, facts(), mode="enforce")
    assert (v.verdict, v.state, v.reasons) == ("release", "success", ())
    assert v.description == "T2 · Release: checks passed"


def test_an_open_incident_in_the_release_holds_it():
    v = evaluate(POLICY, facts(open_incidents=(OpenIncident("pipeline", 61),)), mode="enforce")
    assert (v.verdict, v.state) == ("hold", "pending")
    assert v.description == "T2 · Held: open incident in pipeline (#61)"


def test_ci_running_holds_and_ci_failed_blocks():
    assert evaluate(POLICY, facts(ci="running"), mode="enforce").verdict == "hold"
    blocked = evaluate(
        POLICY, facts(ci="failed", open_incidents=(OpenIncident("pipeline"),)), mode="enforce"
    )
    assert (blocked.verdict, blocked.state) == ("blocked", "failure")
    assert blocked.reasons == ("CI failed on the release commit", "open incident in pipeline")


def test_too_many_failed_deploys_hold_but_too_few_deploys_to_judge_do_not():
    held = evaluate(POLICY, facts(recent_deploys=5, failed_deploys=2), mode="enforce")
    assert held.verdict == "hold"
    assert "2 of 5 deploys in 7 days caused incidents (over 30%)" in held.description
    assert evaluate(POLICY, facts(recent_deploys=2, failed_deploys=2), mode="enforce").verdict == (
        "release"
    )
    assert evaluate(POLICY, facts(recent_deploys=10, failed_deploys=3), mode="enforce").verdict == (
        "release"
    )


def test_t3_goes_to_the_signoff_environment_and_waits_for_a_simulated_signoff():
    real = evaluate(POLICY, facts(tier="T3"), mode="enforce")
    assert (real.verdict, real.environment) == ("release", "production-signoff")
    assert real.description == "T3 · Release: checks passed; approve the deployment in GitHub"
    waiting = evaluate(POLICY, facts(tier="T3", signoff=False), mode="enforce")
    assert (waiting.verdict, waiting.reasons) == ("hold", ("waiting for sign-off (simulated)",))
    signed = evaluate(POLICY, facts(tier="T3", signoff=True), mode="enforce")
    assert signed.description == "T3 · Release: checks passed and signed off (simulated)"


def test_shadow_mode_always_passes_and_says_what_enforce_would_do():
    v = evaluate(POLICY, facts(open_incidents=(OpenIncident("pipeline", 61),)), mode="shadow")
    assert (v.verdict, v.state, v.would_be) == ("hold", "success", "pending")
    assert v.description.startswith("T2 · Shadow (would be pending). Held:")


def test_a_release_takes_its_highest_tier_and_an_unknown_tier_fails_closed():
    assert release_tier(["T0", "T2", "T1"], "T2") == "T2"
    assert release_tier(["T0", None], "T2") == "T2"
    assert release_tier([], "T2") == "T2"


def test_the_policy_rejects_a_bad_release_setting(tmp_path):
    from sdlc.tiers import POLICY as FILE
    from sdlc.tiers import PolicyError

    text = FILE.read_text(encoding="utf-8")
    bad = tmp_path / "tiers.yaml"
    bad.write_text(text.replace("release: signoff", "release: never"), encoding="utf-8")
    with pytest.raises(PolicyError, match="release must be one of"):
        load_policy(bad)
    bad.write_text(text.replace("release: signoff", "release: automatic"), encoding="utf-8")
    with pytest.raises(PolicyError, match="higher tier can't ask less"):
        load_policy(bad)


# --- the simulated history ---------------------------------------------------------------------


def test_the_history_holds_releases_and_ships_them_later(db, history):
    rows = list(db.scalars(select(AgentDecision).where(AgentDecision.agent == "release_gate")))
    verdicts = [r.output["verdict"] for r in rows]
    assert verdicts.count("release") == history["deployments"]
    assert "hold" in verdicts
    assert all(r.subject_source == "synthetic" and r.subject_type == "release" for r in rows)
    held = [r for r in rows if r.output["verdict"] == "hold"]
    assert all(r.output["reasons"] for r in held)
    # A held release doesn't deploy that day; its PRs ship with a later release.
    shipped = {n for r in rows if r.output["verdict"] == "release" for n in r.output["prs"]}
    for r in held:
        later = [
            x for x in rows if x.created_at > r.created_at and x.output["verdict"] == "release"
        ]
        if later:
            assert set(r.output["prs"]) <= shipped


def test_every_simulated_incident_follows_the_deploy_that_caused_it(db, history):
    for incident in db.scalars(select(Incident)):
        deploy = db.get(Deployment, incident.deployment_id)
        assert incident.opened_at > deploy.deployed_at


# --- real releases -----------------------------------------------------------------------------


def _merged_pr(gh, number, sha, module_file, merged_at):
    gh.open_pr(number, f"head-{number}", files=[module_file], title=f"Change {number}")
    gh.merge(number, sha, merged_at=merged_at)


def _runner(gh, mode="enforce"):
    from sdlc.release_runner import ReleaseRunner

    return ReleaseRunner(gh.client(), POLICY, mode)


def test_a_real_release_is_held_by_an_open_incident_until_it_closes(db):
    gh = FakeGitHub()
    _merged_pr(gh, 7, "m7", "apps/api/app/routers/pipeline.py", "2026-09-21T10:00:00Z")
    gh.ci("m7", {job: ["success"] for job in CI_JOBS})
    gh.open_incident(61, "pipeline")
    gh.deploy_run("m7")
    runner = _runner(gh)
    now = datetime(2026, 9, 21, 12, 0)

    assert runner.poll_once(now)["assessed"] == 1
    status = gh.last_status("m7")
    assert (status["context"], status["state"]) == ("release-gate", "pending")
    assert status["description"] == "T2 · Held: open incident in pipeline (#61)"
    assert runner.poll_once(now)["assessed"] == 0  # nothing changed: no new row, no new post
    assert len(gh.statuses) == 1

    gh.issues[61].update(state="closed", closed_at="2026-09-21T12:30:00Z")
    runner.poll_once(now)
    assert gh.last_status("m7")["state"] == "success"
    rows = list(db.scalars(select(AgentDecision).where(AgentDecision.agent == "release_gate")))
    assert [(r.output["verdict"], r.attempt, r.subject_id, r.head_sha) for r in rows] == [
        ("hold", 1, 7, "m7"),
        ("release", 2, 7, "m7"),
    ]
    # The incident issue is an incident, not work: no Issue row, and the triage agent skips it.
    assert db.scalar(select(Issue).where(Issue.number == 61)) is None
    assert db.scalar(select(Incident).where(Incident.external_id == "issue-61")).resolved_at


def test_a_release_waits_for_ci_on_its_commit_then_releases(db):
    gh = FakeGitHub()
    _merged_pr(gh, 8, "m8", "apps/api/app/routers/forecast.py", "2026-09-21T10:00:00Z")
    gh.ci("m8", {job: [None] for job in CI_JOBS})
    gh.deploy_run("m8")
    runner = _runner(gh)
    runner.poll_once(datetime(2026, 9, 21, 12))
    assert gh.last_status("m8")["description"] == "T2 · Held: waiting for CI on the release commit"
    gh.jobs = {k: [{**j, "conclusion": "success"} for j in v] for k, v in gh.jobs.items()}
    runner.poll_once(datetime(2026, 9, 21, 12, 5))
    assert gh.last_status("m8")["state"] == "success"


def test_shadow_mode_posts_success_and_finished_runs_are_left_alone(db):
    gh = FakeGitHub()
    _merged_pr(gh, 9, "m9", "apps/api/app/routers/pipeline.py", "2026-09-21T10:00:00Z")
    gh.ci("m9", {job: ["success"] for job in CI_JOBS})
    gh.open_incident(62, "pipeline")
    gh.deploy_run("m9")
    _runner(gh, mode="shadow").poll_once(datetime(2026, 9, 21, 12))
    assert gh.last_status("m9")["state"] == "success"
    assert "would be pending" in gh.last_status("m9")["description"]

    done = FakeGitHub()
    done.deploy_run("zzz", status="completed")
    assert _runner(done).poll_once()["releases"] == 0
    assert done.statuses == []
    assert _runner(done, mode="off").poll_once() == {"mode": "off"}


def test_a_real_deploy_is_collected_and_the_next_release_starts_after_it(db):
    from sdlc.release_runner import release_prs

    gh = FakeGitHub()
    _merged_pr(gh, 7, "m7", "apps/web/src/views/LeadsView.vue", "2026-09-21T10:00:00Z")
    _merged_pr(gh, 8, "m8", "apps/web/src/views/LeadsView.vue", "2026-09-21T11:00:00Z")
    _merged_pr(gh, 9, "m9", "apps/web/src/views/LeadsView.vue", "2026-09-21T13:00:00Z")
    gh.deployment("m8", at="2026-09-21T12:00:00Z")
    gh.deploy_run("m9")
    gh.ci("m9", {job: ["success"] for job in CI_JOBS})
    _runner(gh).poll_once(datetime(2026, 9, 21, 13, 30))

    deploy = db.scalar(select(Deployment).where(Deployment.source == "github"))
    assert (deploy.sha, deploy.status) == ("m8", "success")
    head = db.scalar(select(PullRequest).where(PullRequest.merge_commit_sha == "m9"))
    assert [p.number for p in release_prs(db, head)] == [9]

    # The demo reset deletes deployments on GitHub; the next collection forgets them too.
    gh.deployments = []
    _runner(gh).poll_once(datetime(2026, 9, 21, 13, 31))
    assert db.scalar(select(Deployment).where(Deployment.source == "github")) is None


def test_the_board_moves_a_real_pr_to_production_once_a_deploy_ships_it(db):
    from sdlc.board import build_board

    gh = FakeGitHub()
    _merged_pr(gh, 7, "m7", "apps/api/app/routers/pipeline.py", "2026-09-21T10:00:00Z")
    _merged_pr(gh, 8, "m8", "apps/api/app/routers/pipeline.py", "2026-09-21T11:00:00Z")
    gh.ci("m8", {job: ["success"] for job in CI_JOBS})
    gh.open_incident(61, "pipeline")
    gh.deploy_run("m8")
    _runner(gh).poll_once(datetime(2026, 9, 21, 12))
    cards = {c.pr_number: c for c in build_board(db, now=datetime(2026, 9, 21, 12)).cards}
    assert cards[8].column == "merged"
    assert cards[8].release["verdict"] == "hold"

    gh.issues[61].update(state="closed", closed_at="2026-09-21T12:30:00Z")
    gh.deployment("m7", at="2026-09-21T12:40:00Z")  # an older commit: ships #7, not #8
    _runner(gh).poll_once(datetime(2026, 9, 21, 12, 45))
    cards = {c.pr_number: c for c in build_board(db, now=datetime(2026, 9, 21, 13)).cards}
    assert (cards[7].column, cards[8].column) == ("production", "merged")
