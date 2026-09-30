import json
from datetime import datetime, timedelta

from sqlalchemy import select

from sdlc.agent_runs import AgentRunCollector, parse_record
from sdlc.agents.llm import StructuredLLM
from sdlc.audit import record_decision
from sdlc.board import build_board
from sdlc.issue_runner import IssueRunner
from sdlc.metrics import dora_summary
from sdlc.signals.github import Collector
from sdlc.suite_selector import AGENT as SELECTOR
from sdlc.suite_selector import settle
from sdlc.tables import AgentDecision, Issue, PullRequest
from tests.fakes import FakeAnthropic, FakeGitHub, response, triage_answer

NOW = datetime(2026, 9, 28, 12, 0)


def run_comment(
    run, *, issue=3, outcome="success", tests="true", cost=0.42, by="github-actions[bot]"
):
    record = {
        "run": str(run),
        "action": "build",
        "issue": issue,
        "pr": "",
        "tier": "T1",
        "model": "claude-sonnet-5",
        "outcome": outcome,
        "tests_passed": tests,
        "turns": 17,
        "input_tokens": 1200,
        "output_tokens": 3400,
        "cache_read_tokens": 90000,
        "cache_write_tokens": 8000,
        "cost_usd": cost,
    }
    return {
        "user": {"login": by},
        "created_at": "2026-09-28T11:00:00Z",
        "html_url": f"https://github.com/pragmattie/pragmattie-sync-agentic/issues/{issue}#c{run}",
        "body": f"Agent run (build, `claude-sonnet-5`, {outcome}): 17 turns, ${cost}.\n\n"
        f"<!-- pragmattie-run {json.dumps(record, separators=(',', ':'))} -->",
    }


def implementer_rows(db):
    return list(db.scalars(select(AgentDecision).where(AgentDecision.agent == "implementer")))


# --- the implementer's run records -------------------------------------------------------------


def test_a_run_record_is_read_and_a_bad_one_is_not():
    assert parse_record(run_comment(7)["body"])["cost_usd"] == 0.42
    assert parse_record("no record here") is None
    assert parse_record("<!-- pragmattie-run {not json} -->") is None
    assert parse_record('<!-- pragmattie-run {"run":"7"} -->') is None  # no issue number


def test_each_run_becomes_one_audit_row_with_its_cost(db):
    gh = FakeGitHub()
    gh.repo_comments = [
        run_comment(101),
        run_comment(102, issue=4, outcome="failure", tests="false", cost=1.9),
        run_comment(103, by="someone"),  # not the workflow: ignored
        {
            "user": {"login": "github-actions[bot]"},
            "created_at": "2026-09-28T11:05:00Z",
            "body": "The agents' daily budget is used up.",
        },  # the workflow, but no record
    ]
    collector = AgentRunCollector(gh.client(), "shadow")
    assert collector.poll_once(NOW)["assessed"] == 2
    rows = sorted(implementer_rows(db), key=lambda r: r.subject_id)
    assert [(r.subject_source, r.subject_id, r.head_sha, r.status) for r in rows] == [
        ("agentic", 3, "run-101", "ok"),
        ("agentic", 4, "run-102", "error"),
    ]
    assert (rows[0].model_id, rows[0].input_tokens, rows[0].output_tokens) == (
        "claude-sonnet-5",
        1200,
        3400,
    )
    assert rows[1].output["cost_usd"] == 1.9 and rows[0].tier == "T1"

    assert collector.poll_once(NOW + timedelta(minutes=1))["assessed"] == 0  # seen already
    assert len(implementer_rows(db)) == 2


def test_run_records_are_not_read_in_off_mode(db):
    gh = FakeGitHub()
    gh.repo_comments = [run_comment(101)]
    assert AgentRunCollector(gh.client(), "off").poll_once(NOW) == {"mode": "off"}
    assert gh.requests == [] and implementer_rows(db) == []


# --- the shadow reviewer's verdicts ------------------------------------------------------------


def review_comment(run, *, pr=101, verdict="approve", blockers=0, by="github-actions[bot]"):
    record = {
        "run": str(run),
        "pr": pr,
        "issue": 12,
        "sha": "3d99481aa0",
        "model": "claude-opus-5-5",
        "outcome": "success",
        "verdict": verdict,
        "blockers": blockers,
        "should_fix": 1,
        "criteria_met": 5,
        "criteria": 5,
        "turns": 12,
        "input_tokens": 40,
        "output_tokens": 2100,
        "cost_usd": 0.31,
    }
    return {
        "user": {"login": by},
        "created_at": "2026-09-28T11:00:00Z",
        "updated_at": "2026-09-28T11:30:00Z",
        "html_url": f"https://github.com/pragmattie/pragmattie-sync-agentic/pull/{pr}#c{run}",
        "body": "## AI review (shadow): would approve\n\n"
        f"<!-- pragmattie-review {json.dumps(record, separators=(',', ':'))} -->",
    }


def test_each_reviewed_commit_becomes_one_reviewer_row(db):
    gh = FakeGitHub()
    gh.repo_comments = [
        review_comment(201),
        review_comment(202, pr=102, verdict="request_changes", blockers=2),
        review_comment(203, verdict="none"),  # the reviewer did not finish: an error row
        review_comment(204, by="someone"),  # not the workflow: ignored
    ]
    collector = AgentRunCollector(gh.client(), "shadow")
    assert collector.poll_once(NOW)["assessed"] == 3
    rows = list(
        db.scalars(
            select(AgentDecision)
            .where(AgentDecision.agent == "reviewer")
            .order_by(AgentDecision.head_sha)
        )
    )
    assert [(r.subject_type, r.subject_id, r.head_sha, r.status) for r in rows] == [
        ("pr", 101, "review-201", "ok"),
        ("pr", 102, "review-202", "ok"),
        ("pr", 101, "review-203", "error"),
    ]
    assert rows[0].subject_source == "agentic" and rows[0].model_id == "claude-opus-5-5"
    assert rows[0].action_taken["verdict"] == "approve" and rows[0].output["cost_usd"] == 0.31
    assert rows[1].action_taken["verdict"] == "request_changes" and rows[1].output["blockers"] == 2
    assert rows[2].action_taken["verdict"] is None

    # The comment is rewritten for the next commit: a new run id is a new row, the old one is not.
    gh.repo_comments = [review_comment(201), review_comment(205)]
    assert collector.poll_once(NOW + timedelta(minutes=1))["assessed"] == 1
    assert implementer_rows(db) == []  # a review is never counted as an implementer run


# --- one governance, two repositories ----------------------------------------------------------


def test_the_rebuilds_issues_are_triaged_as_agentic_rows(db):
    gh = FakeGitHub()
    gh.open_issue(12, title="Leads list: filters and search", body="Filter by status and owner.")
    llm = FakeAnthropic(response(triage_answer(module="leads", type="feature", points=3)))
    IssueRunner(gh.client(), StructuredLLM(client=llm), "shadow", "agentic").poll_once(NOW)
    (row,) = db.scalars(select(AgentDecision).where(AgentDecision.agent == "triage"))
    assert (row.subject_source, row.subject_id) == ("agentic", 12)


def test_the_same_number_in_both_repositories_never_collides(db):
    gh = FakeGitHub()
    gh.open_pr(7, "sha-7")
    Collector(db, gh.client()).collect_pull_request(gh.prs[7])
    Collector(db, gh.client(), "agentic").collect_pull_request(gh.prs[7])
    db.commit()
    rows = db.scalars(select(PullRequest).where(PullRequest.number == 7))
    assert sorted(r.source for r in rows) == ["agentic", "github"]


def test_ci_results_are_settled_per_repository(db):
    gh = FakeGitHub()
    jobs = {
        "API (lint + tests)": ["success"],
        "API (migrations on MySQL)": ["success"],
        "Web (tests + build)": ["success"],
        "Orchestrator (lint + tests)": ["success"],
    }
    gh.ci("abc", jobs)
    for source in ("github", "agentic"):
        record_decision(
            db,
            agent=SELECTOR,
            agent_version="v1",
            subject_type="pr",
            subject_source=source,
            subject_id=7,
            trigger="poll",
            now=NOW,
            head_sha="abc",
            tier="T1",
            status="ok",
            output={"suites": ["api"], "skipped": ["web"]},
        )
    db.commit()
    assert settle(db, gh.client(), NOW, "agentic") == 1
    results = db.scalars(select(AgentDecision).where(AgentDecision.trigger == "ci_result")).all()
    assert [r.subject_source for r in results] == ["agentic"]


def test_v1s_board_and_metrics_leave_the_rebuild_out(db):
    for source, open_days in (("github", 2), ("agentic", 6)):
        db.add(
            Issue(
                source=source,
                external_id=f"issue-{source}",
                number=5,
                title="Open work",
                state="open",
                created_at=NOW - timedelta(days=1),
            )
        )
        db.add(
            PullRequest(
                source=source,
                external_id=f"pr-{source}",
                number=9,
                title="Merged",
                state="merged",
                created_at=NOW - timedelta(days=open_days),
                merged_at=NOW - timedelta(days=1),
            )
        )
    db.commit()
    assert {c.source for c in build_board(db, now=NOW).cards} == {"github"}
    assert {c.source for c in build_board(db, now=NOW, source="agentic").cards} == {"agentic"}
    lead = dora_summary(db, NOW, days=7)["current"]["lead_time_hours"]
    assert lead == 24.0  # v1's PR (1 day); with the rebuild's (5 days) the median would be 72
