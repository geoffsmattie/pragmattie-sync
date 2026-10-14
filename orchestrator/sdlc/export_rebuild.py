"""Export v1's governance record of the agentic rebuild, for the rebuild to read before cutover.

The rebuild compares its own decisions with these (its item 7.2) and imports them into its audit
trail, marked as decided by v1 (7.3). It never reads this repository's code or database: this file
is the whole contract. Only ever SELECTs.

    python -m sdlc.export_rebuild --out rebuild-export.json

The file holds every audit row about the rebuild (`subject_source = "agentic"`), oldest first,
with every column, and the simulated second approvals of its PRs (by PR number). Times are naive
UTC ISO strings, as stored.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.config import get_settings
from sdlc.db import SessionLocal
from sdlc.tables import AgentDecision, Approval, PullRequest

SOURCE = "agentic"
DECISION_FIELDS = (
    "id",
    "created_at",
    "agent",
    "agent_version",
    "model_id",
    "prompt_version",
    "prompt_hash",
    "subject_type",
    "subject_id",
    "head_sha",
    "attempt",
    "trigger",
    "inputs_digest",
    "raw_score",
    "adjustment",
    "final_score",
    "tier",
    "signals",
    "output",
    "action_taken",
    "status",
    "error",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "human_override",
    "supersedes_id",
)


def _iso(value: datetime | None) -> str | None:
    return value.replace(microsecond=0).isoformat() if value else None


def _decision(row: AgentDecision) -> dict:
    record = {field: getattr(row, field) for field in DECISION_FIELDS}
    record["created_at"] = _iso(row.created_at)
    return record


def export(db: Session, repository: str, now: datetime | None = None) -> dict:
    """Every audit row about the rebuild and its PRs' simulated approvals."""
    decisions = db.scalars(
        select(AgentDecision)
        .where(AgentDecision.subject_source == SOURCE)
        .order_by(AgentDecision.id)
    )
    approvals = db.execute(
        select(Approval, PullRequest.number)
        .join(PullRequest, PullRequest.id == Approval.pull_request_id)
        .where(PullRequest.source == SOURCE)
        .order_by(Approval.id)
    )
    return {
        "exported_at": _iso(now or datetime.now(UTC).replace(tzinfo=None)),
        "repository": repository,
        "decisions": [_decision(row) for row in decisions],
        "approvals": [
            {
                "pr": number,
                "approver_id": approval.approver_id,
                "tier": approval.tier,
                "status": approval.status,
                "reason": approval.reason,
                "note": approval.note,
                "requested_at": _iso(approval.requested_at),
                "decided_at": _iso(approval.decided_at),
            }
            for approval, number in approvals
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export v1's record of the agentic rebuild.")
    parser.add_argument("--out", required=True, help="the JSON file to write")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        data = export(db, get_settings().github_repo_agentic)
    Path(args.out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(
        f"Exported {len(data['decisions'])} decisions and {len(data['approvals'])} approvals "
        f"about {data['repository']} to {args.out}."
    )


if __name__ == "__main__":
    main()
