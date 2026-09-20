"""Write the audit trail: exactly one row per agent run, never updated afterwards.

A correction is a new row that points at the one it replaces (`supersedes_id`). Callers write the
row in the same transaction as the action it records, so a decision and its effect can't diverge.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.tables import AgentDecision, PullRequest


def record_decision(
    db: Session,
    *,
    agent: str,
    agent_version: str,
    pr: PullRequest,
    trigger: str,
    now: datetime | None = None,
    **fields,
) -> AgentDecision:
    """Append a decision about `pr`. `fields` are any other AgentDecision columns."""
    decision = AgentDecision(
        created_at=now or datetime.now().replace(microsecond=0),
        agent=agent,
        agent_version=agent_version,
        subject_type="pr",
        subject_source=pr.source,
        subject_id=pr.number,
        trigger=trigger,
        **{"attempt": 1, **fields},
    )
    db.add(decision)
    db.flush()
    return decision


def decisions_for(db: Session, agent: str, pr: PullRequest, head_sha: str) -> list[AgentDecision]:
    """Every attempt this agent made on this commit of this PR, oldest first."""
    return list(
        db.scalars(
            select(AgentDecision)
            .where(
                AgentDecision.agent == agent,
                AgentDecision.subject_type == "pr",
                AgentDecision.subject_source == pr.source,
                AgentDecision.subject_id == pr.number,
                AgentDecision.head_sha == head_sha,
            )
            .order_by(AgentDecision.attempt)
        )
    )
