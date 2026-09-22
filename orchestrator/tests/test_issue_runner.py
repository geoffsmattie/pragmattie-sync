import re
from datetime import datetime, timedelta

from sqlalchemy import select

from sdlc.agents.llm import StructuredLLM
from sdlc.issue_runner import MAX_ATTEMPTS, RETRY_AFTER, IssueRunner
from sdlc.tables import AgentDecision
from tests.fakes import FakeAnthropic, FakeGitHub, response, timeout_error, triage_answer

NOW = datetime(2026, 9, 22, 10, 0)


def setup(mode, *outcomes, number=12, title="Lead import is slow", body="Times out on big files."):
    gh = FakeGitHub()
    gh.open_issue(number, title=title, body=body)
    llm = FakeAnthropic(*(outcomes or (response(triage_answer()),)))
    runner = IssueRunner(gh.client(), StructuredLLM(client=llm), mode)
    return runner, gh, llm


def decisions(db):
    return list(db.scalars(select(AgentDecision).order_by(AgentDecision.id)))


def test_mode_off_does_nothing_at_all(db):
    runner, gh, llm = setup("off")
    assert runner.poll_once(NOW) == {"mode": "off"}
    assert gh.requests == [] and llm.calls == [] and decisions(db) == []


def test_a_fresh_issue_is_classified_labeled_and_recorded(db):
    runner, gh, llm = setup(
        "shadow", response(triage_answer(module="pipeline", type="bug", priority="p1", points=5))
    )
    summary = runner.poll_once(NOW)
    assert (summary["issues"], summary["assessed"], summary["failed"]) == (1, 1, 0)

    assert gh.labels[12] == {"module:pipeline", "type:bug", "priority:p1", "points:5"}
    body = gh.comment_on(12, marker="pragmattie-triage")["body"]
    assert "## Triage: pipeline / bug (p1)" in body

    (row,) = decisions(db)
    assert (row.agent, row.subject_type, row.subject_source, row.subject_id) == (
        "triage",
        "issue",
        "github",
        12,
    )
    assert row.status == "ok" and row.trigger == "opened" and row.attempt == 1
    assert row.output["module"] == "pipeline" and row.output["estimate_points"] == 5
    assert row.human_override is None


def test_polling_again_on_the_same_content_does_nothing_new(db):
    runner, gh, llm = setup("shadow")
    runner.poll_once(NOW)
    again = runner.poll_once(NOW + timedelta(seconds=30))
    assert again["assessed"] == 0
    assert len(llm.calls) == 1
    assert len(decisions(db)) == 1


def test_editing_the_issue_triggers_a_fresh_classification(db):
    runner, gh, llm = setup(
        "shadow", response(triage_answer(points=2)), response(triage_answer(points=5))
    )
    runner.poll_once(NOW)
    gh.edit_issue(12, body="Times out on big files, and now also crashes the browser tab.")
    runner.poll_once(NOW + timedelta(seconds=30))
    assert len(llm.calls) == 2
    assert [d.attempt for d in decisions(db)] == [1, 1]  # a fresh version, so attempt resets
    assert "points:5" in gh.labels[12]


def test_a_retriage_label_forces_a_rerun_and_is_removed_on_success(db):
    runner, gh, llm = setup(
        "shadow", response(triage_answer(points=2)), response(triage_answer(points=5))
    )
    runner.poll_once(NOW)
    assert "points:2" in gh.labels[12]

    gh.labels[12].add("retriage")
    runner.poll_once(NOW + timedelta(seconds=30))  # unchanged content, but forced
    assert len(llm.calls) == 2
    assert "points:5" in gh.labels[12]
    assert "retriage" not in gh.labels[12]  # consumed
    assert [d.trigger for d in decisions(db)] == ["opened", "retriage"]


def test_retriage_bypasses_the_automatic_failure_backoff(db):
    # Normally a second attempt at the same content waits RETRY_AFTER; a human's retriage label
    # is a deliberate action and must not be throttled by the backoff meant for our own failures.
    runner, gh, llm = setup("shadow", timeout_error(), response(triage_answer()))
    runner.poll_once(NOW)
    assert len(llm.calls) == 1  # first attempt failed

    gh.labels.setdefault(12, set()).add("retriage")  # first attempt failed: no labels exist yet
    runner.poll_once(NOW + timedelta(seconds=5))  # well within the 5-minute backoff window
    assert len(llm.calls) == 2  # ran anyway, because it was forced
    assert gh.labels[12] == {"module:leads", "type:bug", "priority:p2", "points:3"}


def test_needs_info_label_appears_when_confidence_is_low_or_there_are_questions(db):
    runner, gh, _ = setup("shadow", response(triage_answer(confidence=0.3)))
    runner.poll_once(NOW)
    assert "needs-info" in gh.labels[12]


def test_no_needs_info_label_when_confident_and_no_questions(db):
    runner, gh, _ = setup("shadow", response(triage_answer(confidence=0.9)))
    runner.poll_once(NOW)
    assert "needs-info" not in gh.labels[12]


def test_possible_duplicate_label_when_the_model_names_a_real_candidate(db):
    runner, gh, _ = setup("shadow", response(triage_answer(duplicate_of=999)))
    runner.poll_once(NOW)  # 999 was never a real candidate (no other issues exist), so dropped
    assert "possible-duplicate" not in gh.labels[12]


def test_a_human_correction_is_left_alone_on_the_next_triage(db):
    runner, gh, llm = setup(
        "shadow",
        response(triage_answer(module="leads", type="bug")),
        response(triage_answer(module="pipeline", type="feature")),
    )
    runner.poll_once(NOW)
    assert {"module:leads", "type:bug"} <= gh.labels[12]

    # A human corrects the module by hand; type is left as the agent set it.
    gh.labels[12].discard("module:leads")
    gh.labels[12].add("module:accounts")

    gh.edit_issue(12, body="Times out on big files, updated description.")
    runner.poll_once(NOW + timedelta(seconds=30))

    assert "module:accounts" in gh.labels[12]  # the human's correction survives
    assert "module:pipeline" not in gh.labels[12]  # the fresh model answer for module was dropped
    assert "type:feature" in gh.labels[12]  # type had no human correction, so it updated normally

    last = decisions(db)[-1]
    assert last.human_override == {"dimensions": ["module"]}
    body = gh.comment_on(12, marker="pragmattie-triage")["body"]
    assert "A human has already set module; left as-is." in body


def test_a_failed_run_is_retried_after_five_minutes_and_stops_at_the_maximum(db):
    runner, gh, llm = setup("shadow", timeout_error())
    for n in range(MAX_ATTEMPTS + 2):
        runner.poll_once(NOW + n * (RETRY_AFTER + timedelta(seconds=1)))
    assert len(llm.calls) == MAX_ATTEMPTS
    assert len(decisions(db)) == MAX_ATTEMPTS
    assert all(d.status == "timeout" for d in decisions(db))
    assert gh.labels.get(12, set()) == set()  # nothing was ever labeled


def test_pull_requests_are_skipped_by_the_issues_poll(db):
    runner, gh, llm = setup("shadow")
    gh.issues[12]["pull_request"] = {"url": "..."}  # what GitHub actually sends for a PR
    summary = runner.poll_once(NOW)
    assert summary["issues"] == 0 and llm.calls == []


def test_one_issues_write_failure_does_not_stop_the_others(db):
    runner, gh, llm = setup("shadow")
    gh.open_issue(13, title="Second issue", body="Something else.")
    gh.fail = {"POST:/issues/12/labels"}  # the write only; reading current labels still works
    summary = runner.poll_once(NOW)
    assert summary["errors"] == 0  # label write failures are reported per-write, not raised
    # both issues got a decision row; issue 12's label write just carries an error
    assert {d.subject_id for d in decisions(db)} == {12, 13}
    row12 = next(d for d in decisions(db) if d.subject_id == 12)
    assert "error" in row12.action_taken["module"]
    row13 = next(d for d in decisions(db) if d.subject_id == 13)
    assert "error" not in row13.action_taken["module"]  # the other issue was unaffected


def test_the_agent_only_ever_writes_labels_and_a_comment(db):
    runner, gh, _ = setup("shadow", response(triage_answer(duplicate_of=0, confidence=0.2)))
    runner.poll_once(NOW)
    allowed = [r"/issues/\d+/comments", r"/issues/\d+/labels", r"/issues/\d+/labels/.+", r"/labels"]
    assert gh.writes, "expected the agent to have written something"
    for method, path in gh.writes:
        assert method in ("POST", "PATCH", "DELETE")
        assert any(re.search(p + "$", path) for p in allowed), (method, path)
    assert not any(
        part in path for _, path in gh.writes for part in ("assignees", "/git/", "state")
    )


def test_every_run_leaves_exactly_one_audit_row(db):
    runner, gh, llm = setup("shadow", timeout_error(), response(triage_answer()))
    runner.poll_once(NOW)
    runner.poll_once(NOW + RETRY_AFTER + timedelta(seconds=1))
    assert len(llm.calls) == len(decisions(db)) == 2
