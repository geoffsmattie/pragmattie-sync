"""Write the audit trail: exactly one row per agent run, never updated afterwards.

A correction is a new row that points at the one it replaces (`supersedes_id`). Callers write the
row in the same transaction as the action it records, so a decision and its effect can't diverge.
"""

from datetime import datetime

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
        **fields,
    )
    db.add(decision)
    db.flush()
    return decision
