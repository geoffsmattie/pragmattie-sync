"""The test selector's audit trail and track record (the rules live in sdlc/agents/suite_select.py).

Runs inside the PR risk agent's poll (sdlc/runner.py), so it needs no process of its own and obeys
the same ORCHESTRATOR_MODE. Every row is an ordinary audit row with agent `test_selector`:

  trigger poll         the recommendation made when the PR risk agent assessed a commit
  trigger tier_change  a new recommendation because a person changed the tier (`/tier`)
  trigger ci_result    what CI actually did on that commit, once every job has finished:
                       status `missed` when a job it would have skipped really failed, else `ok`

CI still runs every job (recommendation only), so the ci_result rows are a fair test: they show
how often skipping would have been safe, and how many CI minutes it would have saved.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.suite_selector report      # the track record so far
"""

import argparse
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdlc.agents.suite_select import (
    AGENT,
    AGENT_VERSION,
    CI_SUITES,
    Selection,
    flaky_suites,
    select_suites,
    with_flaky,
)
from sdlc.audit import record_decision
from sdlc.github_client import GitHubClient, parse_time
from sdlc.signals.github import JOB_SUITES
from sdlc.tables import AgentDecision, PullRequest
from sdlc.tiers import Policy

RESULT = "ci_result"
SETTLE_WINDOW = timedelta(days=7)  # stop waiting for CI on a commit after this
MAX_PATHS = 300


def recommend(
    db: Session,
    pr: PullRequest,
    sha: str,
    paths: list[str],
    *,
    tier: str,
    policy: Policy,
    assessed: bool,
    now: datetime,
    trigger: str = "poll",
) -> Selection:
    """Choose the suites for this commit and record the choice."""
    selection = select_suites(paths, tier=tier, policy=policy, assessed=assessed)
    selection = with_flaky(selection, flaky_suites(db, now))
    record_decision(
        db,
        agent=AGENT,
        agent_version=AGENT_VERSION,
        subject_type="pr",
        subject_source=pr.source,
        subject_id=pr.number,
        trigger=trigger,
        now=now,
        head_sha=sha,
        attempt=_next_attempt(db, pr.source, pr.number, sha),
        tier=tier,
        output={**selection.as_record(), "paths": paths[:MAX_PATHS]},
        action_taken={"shown_in": "the risk comment's Tests section"},
        status="ok",
    )
    return selection


def _next_attempt(db: Session, source: str, number: int, sha: str) -> int:
    """The audit table keeps one row per commit per attempt, so each row here takes the next."""
    count = db.scalar(
        select(func.count()).where(
            AgentDecision.agent == AGENT,
            AgentDecision.subject_type == "pr",
            AgentDecision.subject_source == source,
            AgentDecision.subject_id == number,
            AgentDecision.head_sha == sha,
        )
    )
    return count + 1


def latest_recommendation(db: Session, pr: PullRequest, sha: str) -> AgentDecision | None:
    return db.scalar(
        select(AgentDecision)
        .where(
            AgentDecision.agent == AGENT,
            AgentDecision.subject_type == "pr",
            AgentDecision.subject_source == pr.source,
            AgentDecision.subject_id == pr.number,
            AgentDecision.head_sha == sha,
            AgentDecision.trigger != RESULT,
        )
        .order_by(AgentDecision.id.desc())
        .limit(1)
    )


# --- the track record ------------------------------------------------------------------------


def unsettled(db: Session, now: datetime) -> list[AgentDecision]:
    """The latest recommendation for each recent commit that has no CI result recorded yet."""
    rows = db.scalars(
        select(AgentDecision)
        .where(AgentDecision.agent == AGENT, AgentDecision.created_at >= now - SETTLE_WINDOW)
        .order_by(AgentDecision.id)
    )
    latest: dict[tuple, AgentDecision] = {}
    settled = set()
    for row in rows:
        key = (row.subject_source, row.subject_id, row.head_sha)
        if row.trigger == RESULT:
            settled.add(key)
        else:
            latest[key] = row
    return [row for key, row in latest.items() if key not in settled]


def ci_results(gh: GitHubClient, sha: str) -> dict[str, dict] | None:
    """Each CI job's final result on this commit, or None while any job hasn't finished.

    A job that failed and then passed on a re-run counts as flaky, and its final result stands.
    """
    attempts: dict[str, list[dict]] = {}
    runs = gh.get("/repos/{repo}/actions/runs", head_sha=sha, per_page=100)["workflow_runs"]
    for run in sorted(runs, key=lambda r: r.get("created_at") or ""):
        jobs = gh.paginate(
            f"/repos/{{repo}}/actions/runs/{run['id']}/jobs", key="jobs", filter="all"
        )
        for job in sorted(jobs, key=lambda j: j.get("run_attempt", 1)):
            if suite := JOB_SUITES.get(job["name"]):
                attempts.setdefault(suite, []).append(job)
    results = {}
    for suite in CI_SUITES:
        jobs = attempts.get(suite)
        if not jobs or not jobs[-1].get("conclusion"):
            return None  # not run yet, or still running
        final = jobs[-1]["conclusion"]
        if final not in ("success", "failure"):
            return None  # cancelled or skipped: wait for a run that finishes
        failed_before = any(j.get("conclusion") == "failure" for j in jobs[:-1])
        results[suite] = {
            "conclusion": final,
            "flaky": final == "success" and failed_before,
            "seconds": _seconds(jobs[-1]),
        }
    return results


def _seconds(job: dict) -> int:
    started, finished = parse_time(job.get("started_at")), parse_time(job.get("completed_at"))
    return int((finished - started).total_seconds()) if started and finished else 0


def settle(db: Session, gh: GitHubClient, now: datetime) -> int:
    """Record the CI result for every recommendation whose commit has finished CI."""
    recorded = 0
    for rec in unsettled(db, now):
        results = ci_results(gh, rec.head_sha)
        if results is None:
            continue
        skipped = rec.output["skipped"]
        missed = [s for s in skipped if results[s]["conclusion"] == "failure"]
        caught = [
            s for s in rec.output["suites"] if results.get(s, {}).get("conclusion") == "failure"
        ]
        record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="pr",
            subject_source=rec.subject_source,
            subject_id=rec.subject_id,
            trigger=RESULT,
            now=now,
            head_sha=rec.head_sha,
            attempt=_next_attempt(db, rec.subject_source, rec.subject_id, rec.head_sha),
            tier=rec.tier,
            output={
                "recommendation_id": rec.id,
                "suites": rec.output["suites"],
                "skipped": skipped,
                "results": results,
                "missed": missed,
                "caught": caught,
                "saved_seconds": sum(results[s]["seconds"] for s in skipped),
            },
            status="missed" if missed else "ok",
        )
        recorded += 1
    return recorded


def report(db: Session) -> dict:
    rows = list(
        db.scalars(
            select(AgentDecision).where(
                AgentDecision.agent == AGENT, AgentDecision.trigger == RESULT
            )
        )
    )
    skipped = sum(len(r.output["skipped"]) for r in rows)
    missed = [(r.subject_id, s) for r in rows for s in r.output["missed"]]
    return {
        "commits": len(rows),
        "jobs_skipped": skipped,
        "jobs_run": sum(len(r.output["suites"]) for r in rows),
        "missed": missed,
        "caught": sum(len(r.output["caught"]) for r in rows),
        "flaky_reruns": sum(
            1 for r in rows for res in r.output["results"].values() if res.get("flaky")
        ),
        "saved_minutes": round(sum(r.output["saved_seconds"] for r in rows) / 60, 1),
    }


def describe(r: dict) -> str:
    if not r["commits"]:
        return "No commits have finished CI since the test selector started recommending."
    lines = [
        f"Test selector track record: {r['commits']} "
        f"{'commit' if r['commits'] == 1 else 'commits'} with CI results.",
        f"  Would have run {r['jobs_run']} jobs and skipped {r['jobs_skipped']}, "
        f"saving about {r['saved_minutes']} CI minutes.",
        f"  Skipped jobs that really failed (misses): {len(r['missed'])}",
    ]
    lines += [f"    PR #{pr}: {suite}" for pr, suite in r["missed"]]
    lines += [
        f"  Failures caught by jobs it would have run: {r['caught']}",
        f"  Jobs that failed and then passed on a re-run (flaky): {r['flaky_reruns']}",
        "  CI still runs every job, so these are what skipping would have done, not what it did.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="The test selector's track record.")
    parser.add_argument("command", choices=["report"])
    parser.parse_args(argv)
    from sdlc.db import SessionLocal

    with SessionLocal() as db:
        print(describe(report(db)))


if __name__ == "__main__":
    main()
