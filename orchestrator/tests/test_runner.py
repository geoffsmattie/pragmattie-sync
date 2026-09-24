import re
from datetime import datetime, timedelta

from sqlalchemy import func, select

from sdlc import approver
from sdlc.agents.llm import StructuredLLM
from sdlc.runner import MAX_ATTEMPTS, RETRY_AFTER, Runner
from sdlc.tables import AgentDecision, PullRequest
from sdlc.tiers import load_policy
from tests.fakes import FakeAnthropic, FakeGitHub, answer, response, timeout_error

NOW = datetime(2026, 9, 21, 10, 0)  # a Monday, working hours
POLICY = load_policy()
LEADS = ["apps/web/src/views/LeadsView.vue", "apps/web/tests/leads.spec.js"]  # rubric scores 15
PIPELINE = ["apps/api/app/api/opportunities.py", "apps/api/tests/test_opps.py"]  # floor T2
MIGRATION = ["apps/api/alembic/versions/0005_x.py", "apps/api/tests/test_x.py"]  # floor T3


def setup(mode, *outcomes, files=LEADS, adjustment=0, pr=7, sha="sha1"):
    gh = FakeGitHub()
    gh.open_pr(pr, sha, files=files)
    llm = FakeAnthropic(*(outcomes or (response(answer(adjustment=adjustment)),)))
    runner = Runner(gh.client(), StructuredLLM(client=llm), POLICY, mode)
    return runner, gh, llm


def decisions(db):
    """Every audit row except the test selector's (tests/test_test_select.py covers those)."""
    return list(
        db.scalars(
            select(AgentDecision)
            .where(AgentDecision.agent != "test_selector")
            .order_by(AgentDecision.id)
        )
    )


def test_mode_off_does_nothing_at_all(db):
    runner, gh, llm = setup("off")
    assert runner.poll_once(NOW) == {"mode": "off"}
    assert gh.requests == []  # not even a read
    assert llm.calls == []
    assert decisions(db) == []


def test_shadow_mode_comments_labels_records_and_always_passes(db):
    runner, gh, llm = setup("shadow", adjustment=10)  # rubric 15 + 10 = 25 -> T1
    summary = runner.poll_once(NOW)
    assert (summary["assessed"], summary["failed"], summary["errors"]) == (1, 0, 0)

    body = gh.comment_on(7)["body"]
    assert "Risk review: T1" in body and "Shadow mode." in body
    assert gh.labels[7] == {"tier:T1"}
    status = gh.last_status("sha1")
    assert status["state"] == "success" and "Shadow mode" in status["description"]

    (row,) = decisions(db)
    assert (row.agent, row.status, row.tier, row.attempt, row.head_sha) == (
        "pr_risk",
        "ok",
        "T1",
        1,
        "sha1",
    )
    assert (row.raw_score, row.adjustment, row.final_score) == (15, 10, 25)
    assert (row.model_id, row.prompt_version) == ("claude-sonnet-5", "pr-risk-v1")
    assert (row.input_tokens, row.output_tokens) == (1200, 150)
    assert row.action_taken["comment"]["created"] is True and row.action_taken["mode"] == "shadow"
    assert row.output["model_answer"]["adjustment"] == 10 and row.output["clamped"] is False

    # Polling again on the same commit does nothing new: one run, one row, one comment.
    again = runner.poll_once(NOW + timedelta(seconds=30))
    assert again["assessed"] == 0 and len(llm.calls) == 1
    assert len(decisions(db)) == 1 and len(gh.comments[7]) == 1


def test_enforce_t0_needs_nobody(db):
    runner, gh, _ = setup("enforce")  # rubric 15 -> T0
    runner.poll_once(NOW)
    status = gh.last_status("sha1")
    assert status["state"] == "success" and "requirements met" in status["description"]
    assert "doesn't need to act" in gh.comment_on(7)["body"]


def test_enforce_t1_waits_for_the_signoff_box_then_passes(db):
    runner, gh, _ = setup("enforce", adjustment=10)
    runner.poll_once(NOW)
    assert gh.last_status("sha1")["state"] == "pending"

    gh.tick(7, "Human sign-off")
    runner.poll_once(NOW + timedelta(seconds=30))
    assert gh.last_status("sha1")["state"] == "success"
    assert "- [x] **Human sign-off" in gh.comment_on(7)["body"]


def test_enforce_t3_needs_signoff_qa_and_the_simulated_second_approval(db):
    runner, gh, _ = setup("enforce", files=MIGRATION)
    runner.poll_once(NOW)
    assert (
        "waiting for human sign-off, manual QA, simulated second approval"
        in (gh.last_status("sha1")["description"])
    )
    (pending,) = approver.pending(db)
    assert pending.tier == "T3" and pending.source == "simulated"

    gh.tick(7, "Human sign-off")
    gh.tick(7, "Manual QA done")
    runner.poll_once(NOW + timedelta(seconds=30))
    assert gh.last_status("sha1")["state"] == "pending"  # still missing the second approval
    assert "waiting for simulated second approval" in gh.last_status("sha1")["description"]

    pr = db.scalar(select(PullRequest).where(PullRequest.source == "github"))
    simulated = approver.load_approvers()["simulated-second-human"]
    approver.approve(db, pr, simulated, note="Geoff, by hand")
    db.commit()
    runner.poll_once(NOW + timedelta(seconds=60))
    assert gh.last_status("sha1")["state"] == "success"
    assert "Simulated second approval: **approved**" in gh.comment_on(7)["body"]


def test_a_new_push_is_assessed_again_and_the_old_ticks_do_not_carry_over(db):
    runner, gh, llm = setup("enforce", adjustment=10)
    runner.poll_once(NOW)
    gh.tick(7, "Human sign-off")
    runner.poll_once(NOW + timedelta(seconds=30))
    assert gh.last_status("sha1")["state"] == "success"

    gh.push(7, "sha2")
    runner.poll_once(NOW + timedelta(seconds=60))
    assert len(llm.calls) == 2
    assert gh.last_status("sha2")["state"] == "pending"  # nothing signed off on the new commit
    body = gh.comment_on(7)["body"]
    assert "<!-- head:sha2 -->" in body and "- [ ] **Human sign-off" in body
    assert [d.head_sha for d in decisions(db)] == ["sha1", "sha2"]


def test_a_failed_run_fails_closed_then_retries_after_five_minutes(db):
    runner, gh, llm = setup("enforce", timeout_error(), response(answer(adjustment=10)))
    runner.poll_once(NOW)
    assert gh.last_status("sha1")["state"] == "failure"
    (first,) = decisions(db)
    assert (first.status, first.attempt, first.tier) == ("timeout", 1, "T2")  # fallback tier
    assert "could not score" in gh.comment_on(7)["body"]

    runner.poll_once(NOW + timedelta(minutes=2))
    assert len(llm.calls) == 1  # too soon to try again

    runner.poll_once(NOW + RETRY_AFTER + timedelta(seconds=1))
    assert [(d.attempt, d.status) for d in decisions(db)] == [(1, "timeout"), (2, "ok")]
    assert gh.last_status("sha1")["state"] == "pending"  # scored now; waiting for the sign-off


def test_retries_stop_after_the_maximum_and_the_check_stays_failed(db):
    runner, gh, llm = setup("enforce", timeout_error())
    for n in range(MAX_ATTEMPTS + 2):
        runner.poll_once(NOW + n * (RETRY_AFTER + timedelta(seconds=1)))
    assert len(llm.calls) == MAX_ATTEMPTS
    assert len(decisions(db)) == MAX_ATTEMPTS
    assert gh.last_status("sha1")["state"] == "failure"


def test_draft_prs_wait_until_they_are_ready_for_review(db):
    runner, gh, llm = setup("shadow")
    gh.prs[7]["draft"] = True
    assert runner.poll_once(NOW)["prs"] == 0
    assert llm.calls == [] and gh.writes == [] and decisions(db) == []
    gh.prs[7]["draft"] = False
    assert runner.poll_once(NOW)["assessed"] == 1


def test_one_prs_github_error_does_not_stop_the_others(db):
    runner, gh, llm = setup("shadow")
    gh.open_pr(8, "sha8", files=LEADS)
    gh.fail = {"/pulls/7/files"}  # PR 7 can't even be collected
    summary = runner.poll_once(NOW)
    assert summary["errors"] == 1 and summary["assessed"] == 1
    assert gh.comment_on(8) is not None and gh.comment_on(7) is None


def test_the_agent_only_ever_writes_a_comment_a_label_and_a_status(db):
    runner, gh, _ = setup("enforce", files=MIGRATION, adjustment=15)
    runner.poll_once(NOW)
    gh.tick(7, "Human sign-off")
    runner.poll_once(NOW + timedelta(seconds=30))
    gh.push(7, "sha2")
    runner.poll_once(NOW + timedelta(seconds=60))

    allowed = [
        ("POST", r"/issues/\d+/comments"),
        ("PATCH", r"/issues/comments/\d+"),
        ("POST", r"/statuses/\w+"),
        ("POST", r"/labels"),
        ("POST", r"/issues/\d+/labels"),
        ("DELETE", r"/issues/\d+/labels/.+"),
    ]
    assert gh.writes, "expected the agent to have written something"
    for method, path in gh.writes:
        assert any(method == m and re.search(p + "$", path) for m, p in allowed), (method, path)
    assert not any(part in path for _, path in gh.writes for part in ("merge", "reviews", "/git/"))


def test_every_run_leaves_exactly_one_audit_row(db):
    runner, gh, llm = setup("shadow", timeout_error(), response(answer()))
    runner.poll_once(NOW)
    runner.poll_once(NOW + RETRY_AFTER + timedelta(seconds=1))
    runner.poll_once(NOW + RETRY_AFTER + timedelta(minutes=1))
    assert len(llm.calls) == len(decisions(db)) == 2
    # Plus the test selector's recommendation for each run: every job while the run failed.
    selector = db.scalars(select(AgentDecision).where(AgentDecision.agent == "test_selector"))
    assert [len(r.output["suites"]) for r in selector] == [4, 1]
    assert db.scalar(select(func.count()).select_from(AgentDecision)) == 4


def look(runner, command, **kwargs):
    from argparse import Namespace

    from sdlc.runner import _look

    _look(runner, Namespace(command=command, number=7, **kwargs))


def test_dry_run_shows_the_request_and_cost_but_calls_nothing(db, capsys):
    runner, gh, llm = setup("shadow")
    look(runner, "dry-run")
    out = capsys.readouterr().out
    assert "claude-sonnet-5" in out and "input tokens" in out and "ceiling of roughly $" in out
    assert "nothing was sent to Claude" in out
    assert llm.calls == [] and gh.writes == [] and decisions(db) == []


def test_try_does_not_call_the_api_without_yes(db, capsys):
    runner, gh, llm = setup("shadow")
    look(runner, "try", yes=False)
    assert "Add --yes" in capsys.readouterr().out
    assert llm.calls == []


def test_try_with_yes_calls_once_and_records_only_a_trial_row(db, capsys):
    runner, gh, llm = setup("shadow", adjustment=6)
    look(runner, "try", yes=True)
    out = capsys.readouterr().out
    assert len(llm.calls) == 1
    assert "Status: ok" in out and "adjustment 6" in out and "Tokens: 1200 in, 150 out" in out
    assert "recorded as a trial audit row" in out
    assert gh.writes == []
    (row,) = decisions(db)
    assert (row.trigger, row.status, row.subject_id, row.head_sha) == ("trial", "ok", 7, None)
    assert (row.input_tokens, row.output_tokens, row.model_id) == (1200, 150, "claude-sonnet-5")
    assert row.tier is None and row.final_score is None  # counted for cost, not as a decision


def test_a_trial_run_never_stands_in_for_the_real_assessment(db, capsys):
    runner, gh, llm = setup("shadow", response(answer()), response(answer()))
    look(runner, "try", yes=True)
    summary = runner.poll_once(NOW)
    assert summary["assessed"] == 1 and len(llm.calls) == 2
    assert [d.trigger for d in decisions(db)] == ["trial", "poll"]
    assert gh.labels[7] == {"tier:T0"}
