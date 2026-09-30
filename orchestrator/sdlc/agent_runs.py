"""The implementer agent's runs in the rebuild repository, recorded in the audit trail.

The rebuild's implementer workflow (`.github/workflows/implement.yml` in pragmattie-sync-agentic)
posts a machine-readable record on the issue after every run: an HTML comment
`<!-- pragmattie-run {...} -->` holding the run id, what it did (plan, build or revise), the tier,
model, outcome, turns, tokens and cost. This reads those comments and writes one audit row per run
(`agent = implementer`, `subject_type = issue`, `subject_source = agentic`, `head_sha = run-<id>`),
so agent runs sit in the decision log beside every other agent decision, with their cost.

The rebuild's reviewer workflow (`review.yml`, in shadow) does the same on the pull request, with
`<!-- pragmattie-review {...} -->`: its verdict (approve or request_changes), how many blockers
it found and its cost. Each reviewed commit becomes one row (`agent = reviewer`,
`subject_type = pr`, `head_sha = review-<run id>`), so its verdicts can be compared with the
person's decisions before any review is delegated.

Only comments by `github-actions[bot]` count: that is the workflow's own identity, which nobody
else can post as. No Claude calls; one GitHub read per poll.
"""

import json
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdlc.audit import record_decision
from sdlc.github_client import GitHubClient, parse_time
from sdlc.tables import AgentDecision

AGENT = "implementer"
AGENT_VERSION = "v1"
TRIGGER = "workflow"
WORKFLOW_BOT = "github-actions[bot]"
RECORD = re.compile(r"<!-- pragmattie-run (\{.*?\}) -->")
REVIEWER = "reviewer"
REVIEW_RECORD = re.compile(r"<!-- pragmattie-review (\{.*?\}) -->")
VERDICTS = ("approve", "request_changes")
TIERS = ("T0", "T1", "T2", "T3")
FIRST_LOOK = timedelta(days=30)  # how far back the first poll reads


def parse_record(body: str) -> dict | None:
    """The run record in a comment body, or None when there isn't a valid one."""
    match = RECORD.search(body or "")
    if not match:
        return None
    try:
        record = json.loads(match[1])
        int(record["issue"])
        str(record["run"])
    except (ValueError, KeyError, TypeError):
        return None
    return record


def parse_review(body: str) -> dict | None:
    """The reviewer's record in a comment body, or None when there isn't a valid one."""
    match = REVIEW_RECORD.search(body or "")
    if not match:
        return None
    try:
        record = json.loads(match[1])
        int(record["pr"])
        str(record["run"])
    except (ValueError, KeyError, TypeError):
        return None
    return record


def succeeded(record: dict) -> bool:
    return record.get("outcome") == "success" and record.get("tests_passed") != "false"


class AgentRunCollector:
    def __init__(self, gh: GitHubClient, mode: str, source: str = "agentic"):
        self.gh = gh
        self.mode = mode
        self.source = source
        self._since: datetime | None = None

    def poll_once(self, now: datetime | None = None) -> dict:
        if self.mode == "off":
            return {"mode": "off"}
        from sdlc.db import SessionLocal

        now = now or datetime.now().replace(microsecond=0)
        with SessionLocal() as db:
            since = self._since or self._resume_from(db, now)
            recorded = 0
            for comment in self.gh.paginate(
                "/repos/{repo}/issues/comments",
                since=since.isoformat() + "Z",
                sort="created",
                direction="asc",
            ):
                if (comment.get("user") or {}).get("login") != WORKFLOW_BOT:
                    continue
                body = comment.get("body") or ""
                record = parse_record(body)
                if record and self.record(db, record, comment):
                    recorded += 1
                review = parse_review(body)
                if review and self.record_review(db, review, comment):
                    recorded += 1
            db.commit()
        # Comments can land while a poll runs: look back a little each time; the run id dedupes.
        self._since = now - timedelta(minutes=10)
        return {"mode": self.mode, "assessed": recorded}

    def _resume_from(self, db: Session, now: datetime) -> datetime:
        last = db.scalar(
            select(func.max(AgentDecision.created_at)).where(
                AgentDecision.agent.in_((AGENT, REVIEWER)),
                AgentDecision.subject_source == self.source,
            )
        )
        return (last - timedelta(minutes=10)) if last else now - FIRST_LOOK

    def record(self, db: Session, record: dict, comment: dict) -> bool:
        """One audit row per run; a run already recorded is skipped. True when a row was added."""
        issue, head = int(record["issue"]), f"run-{record['run']}"[:40]
        exists = db.scalar(
            select(AgentDecision.id).where(
                AgentDecision.agent == AGENT,
                AgentDecision.subject_type == "issue",
                AgentDecision.subject_source == self.source,
                AgentDecision.subject_id == issue,
                AgentDecision.head_sha == head,
            )
        )
        if exists:
            return False
        tier = record.get("tier")
        record_decision(
            db,
            agent=AGENT,
            agent_version=AGENT_VERSION,
            subject_type="issue",
            subject_source=self.source,
            subject_id=issue,
            trigger=TRIGGER,
            now=parse_time(comment.get("created_at")),
            head_sha=head,
            model_id=record.get("model"),
            tier=tier if tier in TIERS else None,
            input_tokens=int(record.get("input_tokens") or 0),
            output_tokens=int(record.get("output_tokens") or 0),
            output=record,
            action_taken={
                "action": record.get("action"),
                "pr": record.get("pr") or None,
                "comment": comment.get("html_url"),
            },
            status="ok" if succeeded(record) else "error",
            error=(record.get("error") or None) and str(record["error"])[:500],
        )
        return True

    def record_review(self, db: Session, record: dict, comment: dict) -> bool:
        """One audit row per reviewed commit (the comment is rewritten for each; the run id
        tells them apart). True when a row was added."""
        pr, head = int(record["pr"]), f"review-{record['run']}"[:40]
        exists = db.scalar(
            select(AgentDecision.id).where(
                AgentDecision.agent == REVIEWER,
                AgentDecision.subject_type == "pr",
                AgentDecision.subject_source == self.source,
                AgentDecision.subject_id == pr,
                AgentDecision.head_sha == head,
            )
        )
        if exists:
            return False
        verdict = record.get("verdict")
        record_decision(
            db,
            agent=REVIEWER,
            agent_version=AGENT_VERSION,
            subject_type="pr",
            subject_source=self.source,
            subject_id=pr,
            trigger=TRIGGER,
            now=parse_time(comment.get("updated_at") or comment.get("created_at")),
            head_sha=head,
            model_id=record.get("model"),
            input_tokens=int(record.get("input_tokens") or 0),
            output_tokens=int(record.get("output_tokens") or 0),
            output=record,
            action_taken={
                "action": "review (shadow)",
                "verdict": verdict if verdict in VERDICTS else None,
                "commit": record.get("sha"),
                "comment": comment.get("html_url"),
            },
            status="ok" if verdict in VERDICTS else "error",
        )
        return True
