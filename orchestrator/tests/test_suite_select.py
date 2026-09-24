from datetime import datetime, timedelta

from sqlalchemy import select

from sdlc import suite_selector
from sdlc.agents.llm import StructuredLLM
from sdlc.agents.suite_select import (
    CI_SUITES,
    TESTS_END,
    TESTS_START,
    Flaky,
    by_paths,
    flaky_suites,
    replace_section,
    section_lines,
    select_suites,
    with_flaky,
)
from sdlc.runner import SETTLE_EVERY, Runner
from sdlc.tables import AgentDecision, CIRun
from sdlc.tiers import load_policy
from tests.fakes import FakeAnthropic, FakeGitHub, answer, response

NOW = datetime(2026, 9, 21, 10, 0)
POLICY = load_policy()
LEADS = ["apps/web/src/views/LeadsView.vue", "apps/web/tests/leads.spec.js"]  # rubric 15 -> T0
JOBS = {
    "api": "API (lint + tests)",
    "orchestrator": "Orchestrator (lint + tests)",
    "migrations": "API (migrations on MySQL)",
    "web": "Web (tests + build)",
}


def all_pass(**overrides):
    return {JOBS[s]: overrides.get(s, ["success"]) for s in CI_SUITES}


def pick(paths, tier="T0", assessed=True):
    return select_suites(paths, tier=tier, policy=POLICY, assessed=assessed)


# --- the rules -------------------------------------------------------------------------------


def test_web_changes_select_only_the_web_job():
    s = pick(LEADS)
    assert s.suites == ("web",) and s.skipped == ("api", "orchestrator", "migrations")
    assert s.full is None and "apps/web/src/views/LeadsView.vue" in s.reasons["web"]


def test_api_source_also_selects_migrations_but_api_tests_alone_do_not():
    assert pick(["apps/api/app/api/leads.py"]).suites == ("api", "migrations")
    assert pick(["apps/api/tests/test_leads.py"]).suites == ("api",)


def test_orchestrator_rules():
    assert pick(["orchestrator/sdlc/board.py"]).suites == ("orchestrator", "migrations")
    assert pick(["orchestrator/tests/test_board.py"]).suites == ("orchestrator",)
    migration = pick(["orchestrator/alembic/versions/0008_x.py"], tier="T0")
    assert migration.suites == ("orchestrator", "migrations")


def test_docs_only_selects_nothing():
    s = pick(["README.md", "docs/adr/0003.md"])
    assert s.suites == () and s.full is None
    assert "Would run no jobs" in "\n".join(section_lines(s))


def test_ci_workflow_or_an_unknown_path_selects_everything():
    workflow = pick([".github/workflows/ci.yml", "README.md"])
    assert workflow.suites == CI_SUITES and "CI workflow" in workflow.full
    unknown = pick(["apps/web/src/App.vue", "scripts/deploy.sh"])
    assert unknown.suites == CI_SUITES and "scripts/deploy.sh" in unknown.full


def test_full_suite_tiers_and_failed_assessments_select_everything():
    t2 = pick(LEADS, tier="T2")
    assert t2.suites == CI_SUITES and t2.full.startswith("T2 runs the full suite")
    assert pick(LEADS, tier="T1").suites == ("web",)  # T1 is "selected suites"
    failed = pick(LEADS, assessed=False)
    assert failed.suites == CI_SUITES and "couldn't score" in failed.full


def test_by_paths_reports_the_first_reason_per_suite():
    reasons, full = by_paths(["apps/api/app/a.py", "apps/api/app/b.py"])
    assert full is None and reasons["api"] == "code changed in apps/api/app/a.py"


# --- flaky flags -----------------------------------------------------------------------------


def _runs(db, suite, total, flaky, source="synthetic"):
    for i in range(total):
        db.add(
            CIRun(
                source=source,
                external_id=f"{source}-{suite}-{i}",
                suite=suite,
                conclusion="failure" if i < flaky else "success",
                flaky=i < flaky,
                started_at=NOW - timedelta(days=1),
            )
        )
    db.flush()


def test_flaky_needs_enough_runs_and_a_high_enough_rate(db):
    _runs(db, "web", 40, 4)  # 10%: flaky
    _runs(db, "api", 40, 0)  # never
    _runs(db, "orchestrator", 10, 5)  # too few runs to judge
    _runs(db, "integrations-e2e", 40, 20)  # not a real CI job, never flagged
    (flag,) = flaky_suites(db, NOW)
    assert (flag.suite, flag.rate, flag.runs, flag.simulated_runs) == ("web", 0.1, 40, 40)


def test_only_the_selected_jobs_keep_their_flaky_flags():
    flags = (Flaky("web", 0.1, 40, 40), Flaky("api", 0.2, 40, 0))
    s = with_flaky(pick(LEADS), flags)
    assert [f.suite for f in s.flaky] == ["web"]
    text = "\n".join(section_lines(s))
    assert "Possibly flaky: Web" in text and "40 of them simulated" in text


def test_replace_tests_swaps_only_its_own_section():
    body = "\n".join(["head", *section_lines(pick(LEADS)), "tail"])
    updated = replace_section(body, pick(LEADS, tier="T3"))
    assert updated.startswith("head\n") and updated.endswith("\ntail")
    assert "Would run every job: T3" in updated and updated.count(TESTS_START) == 1
    assert replace_section("no section here", pick(LEADS)) == "no section here"
    assert TESTS_END in updated


# --- in the PR risk agent's poll -------------------------------------------------------------


def setup(files=LEADS, sha="sha1"):
    gh = FakeGitHub()
    gh.open_pr(7, sha, files=files)
    llm = FakeAnthropic(response(answer()))
    return Runner(gh.client(), StructuredLLM(client=llm), POLICY, "shadow"), gh


def rows(db, trigger=None):
    query = select(AgentDecision).where(AgentDecision.agent == "test_selector")
    if trigger:
        query = query.where(AgentDecision.trigger == trigger)
    return list(db.scalars(query.order_by(AgentDecision.id)))


def test_the_risk_comment_carries_the_recommendation_and_it_is_audited(db):
    runner, gh = setup()
    runner.poll_once(NOW)
    body = gh.comment_on(7)["body"]
    assert "**Tests** (the test selector's recommendation; CI still runs every job)" in body
    assert "Would run: **Web**" in body and "Would skip: API, Orchestrator, Migrations" in body
    (row,) = rows(db)
    assert (row.trigger, row.head_sha, row.tier, row.status) == ("poll", "sha1", "T0", "ok")
    assert row.output["suites"] == ["web"] and row.output["paths"] == LEADS
    assert not [w for w in gh.writes if "actions" in w[1]]  # it only ever reads CI


def test_a_raised_tier_brings_a_new_recommendation(db):
    runner, gh = setup()
    runner.poll_once(NOW)
    gh.human_comment(7, "/tier T3")
    runner.poll_once(NOW + timedelta(seconds=30))
    first, second = rows(db)
    assert (second.trigger, second.tier, second.output["suites"]) == (
        "tier_change",
        "T3",
        list(CI_SUITES),
    )
    body = gh.comment_on(7)["body"]
    assert (
        "Would run every job: T3 runs the full suite" in body and "Would run: **Web**" not in body
    )
    runner.poll_once(NOW + timedelta(seconds=60))
    assert len(rows(db)) == 2  # nothing new while the tier stays put


def test_ci_results_are_recorded_once_every_job_finishes(db):
    runner, gh = setup()
    runner.poll_once(NOW)
    gh.ci("sha1", all_pass(web=[None]))  # web still running
    runner.poll_once(NOW + SETTLE_EVERY)
    assert rows(db, "ci_result") == []

    gh.jobs[gh.runs["sha1"][0]["id"]][-1]["conclusion"] = "success"
    gh.jobs[gh.runs["sha1"][0]["id"]][-1]["completed_at"] = "2026-09-21T09:03:00Z"
    runner.poll_once(NOW + 2 * SETTLE_EVERY)
    (result,) = rows(db, "ci_result")
    assert result.status == "ok" and result.output["missed"] == []
    assert result.output["saved_seconds"] == 3 * 180  # three skipped jobs, three minutes each

    runner.poll_once(NOW + 3 * SETTLE_EVERY)
    assert len(rows(db, "ci_result")) == 1  # settled once


def test_a_skipped_job_that_failed_is_a_miss_and_a_flaky_one_is_not(db):
    runner, gh = setup()
    runner.poll_once(NOW)
    gh.ci("sha1", all_pass(api=["failure"], orchestrator=["failure", "success"]))
    runner.poll_once(NOW + SETTLE_EVERY)
    (result,) = rows(db, "ci_result")
    assert result.status == "missed" and result.output["missed"] == ["api"]
    assert result.output["results"]["orchestrator"]["flaky"] is True

    report = suite_selector.report(db)
    assert report["missed"] == [(7, "api")] and report["flaky_reruns"] == 1
    text = suite_selector.describe(report)
    assert "misses): 1" in text and "1 commit with CI results" in text


def test_a_failure_in_a_selected_job_counts_as_caught(db):
    runner, gh = setup()
    runner.poll_once(NOW)
    gh.ci("sha1", all_pass(web=["failure"]))
    runner.poll_once(NOW + SETTLE_EVERY)
    assert suite_selector.report(db)["caught"] == 1


def test_the_report_with_nothing_settled():
    assert "No commits" in suite_selector.describe(
        {"commits": 0, "jobs_skipped": 0, "jobs_run": 0, "missed": [], "caught": 0}
    )


def test_synthetic_history_has_the_real_ci_suites(history, db):
    suites = set(db.scalars(select(CIRun.suite).distinct()))
    assert suites == {*CI_SUITES, "integrations-e2e"}
