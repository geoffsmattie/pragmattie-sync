"""Write the audit trail: exactly one row per agent run, never updated afterwards.

A correction is a new row that points at the one it replaces (`supersedes_id`). Callers write the
row in the same transaction as the action it records, so a decision and its effect can't diverge.

`head_sha` names a commit for the PR risk agent; for the triage agent (no commit to point at) it
holds a content-hash version of the issue's title and body instead (see
sdlc/agents/triage_comment.py's `content_version`) — same column, same "which version of the
subject was this decision made about" purpose.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.tables import AgentDecision


def record_decision(
    db: Session,
    *,
    agent: str,
    agent_version: str,
    subject_type: str,
    subject_source: str,
    subject_id: int,
    trigger: str,
    now: datetime | None = None,
    **fields,
) -> AgentDecision:
    """Append a decision about one PR or issue. `fields` are any other AgentDecision columns."""
    decision = AgentDecision(
        created_at=now or datetime.now().replace(microsecond=0),
        agent=agent,
        agent_version=agent_version,
        subject_type=subject_type,
        subject_source=subject_source,
        subject_id=subject_id,
        trigger=trigger,
        **{"attempt": 1, **fields},
    )
    db.add(decision)
    db.flush()
    return decision


def decisions_for(
    db: Session,
    agent: str,
    *,
    subject_type: str,
    subject_source: str,
    subject_id: int,
    head_sha: str,
) -> list[AgentDecision]:
    """Every attempt this agent made at this version of this PR or issue, oldest first."""
    return list(
        db.scalars(
            select(AgentDecision)
            .where(
                AgentDecision.agent == agent,
                AgentDecision.subject_type == subject_type,
                AgentDecision.subject_source == subject_source,
                AgentDecision.subject_id == subject_id,
                AgentDecision.head_sha == head_sha,
            )
            .order_by(AgentDecision.attempt)
        )
    )


def latest_decision(
    db: Session, agent: str, *, subject_type: str, subject_source: str, subject_id: int
) -> AgentDecision | None:
    """The most recent successful decision this agent made about this PR or issue, any version."""
    return db.scalar(
        select(AgentDecision)
        .where(
            AgentDecision.agent == agent,
            AgentDecision.subject_type == subject_type,
            AgentDecision.subject_source == subject_source,
            AgentDecision.subject_id == subject_id,
            AgentDecision.status == "ok",
        )
        .order_by(AgentDecision.created_at.desc())
        .limit(1)
    )
