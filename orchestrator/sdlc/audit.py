"""Write the audit trail: exactly one row per agent run, never updated afterwards.

A correction is a new row that points at the one it replaces (`supersedes_id`). Callers write the
row in the same transaction as the action it records, so a decision and its effect can't diverge.

`head_sha` names a commit for the PR risk agent; for the triage agent (no commit to point at) it
holds a content-hash version of the issue's title and body instead (see
sdlc/agents/triage_comment.py's `content_version`) — same column, same "which version of the
subject was this decision made about" purpose.

A manual `try` (sdlc/runner.py, sdlc/issue_runner.py) records a "trial" row too, so every paid API
call shows up in the token totals. A trial row has no `head_sha`, and every reader that decides
what the agents do next (`decisions_for`, `latest_decision`, the delivery board) skips it: trying
a PR or issue never stands in for, or blocks, the real assessment.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdlc.tables import AgentDecision

TRIAL = "trial"  # the `trigger` of a manual `try` run: counted for cost, ignored for decisions


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
                AgentDecision.trigger != TRIAL,
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
            AgentDecision.trigger != TRIAL,
        )
        .order_by(AgentDecision.created_at.desc())
        .limit(1)
    )


def _filtered(
    db: Session,
    *,
    agent: str | None,
    subject_type: str | None,
    subject_source: str | None,
    status: str | None,
    tier: str | None,
):
    query = select(AgentDecision)
    if agent:
        query = query.where(AgentDecision.agent == agent)
    if subject_type:
        query = query.where(AgentDecision.subject_type == subject_type)
    if subject_source:
        query = query.where(AgentDecision.subject_source == subject_source)
    if status:
        query = query.where(AgentDecision.status == status)
    if tier:
        query = query.where(AgentDecision.tier == tier)
    return query


def list_decisions(
    db: Session,
    *,
    agent: str | None = None,
    subject_type: str | None = None,
    subject_source: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AgentDecision]:
    """The decision log for the web app: every agent run, newest first, any filter combination."""
    query = _filtered(
        db,
        agent=agent,
        subject_type=subject_type,
        subject_source=subject_source,
        status=status,
        tier=tier,
    )
    query = query.order_by(AgentDecision.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(query))


def serialize_decision(d: AgentDecision) -> dict:
    """AgentDecision -> plain JSON-safe dict, the same shape board.py's `serialize` follows."""
    return {
        "id": d.id,
        "created_at": d.created_at.isoformat(),
        "agent": d.agent,
        "agent_version": d.agent_version,
        "model_id": d.model_id,
        "prompt_version": d.prompt_version,
        "prompt_hash": d.prompt_hash,
        "subject_type": d.subject_type,
        "subject_source": d.subject_source,
        "subject_id": d.subject_id,
        "head_sha": d.head_sha,
        "attempt": d.attempt,
        "trigger": d.trigger,
        "raw_score": d.raw_score,
        "adjustment": d.adjustment,
        "final_score": d.final_score,
        "tier": d.tier,
        "signals": d.signals,
        "output": d.output,
        "action_taken": d.action_taken,
        "status": d.status,
        "error": d.error,
        "latency_ms": d.latency_ms,
        "input_tokens": d.input_tokens,
        "output_tokens": d.output_tokens,
        "human_override": d.human_override,
        "supersedes_id": d.supersedes_id,
    }


def count_decisions(
    db: Session,
    *,
    agent: str | None = None,
    subject_type: str | None = None,
    subject_source: str | None = None,
    status: str | None = None,
    tier: str | None = None,
) -> int:
    """Total rows matching the same filters as `list_decisions`, for pagination."""
    query = _filtered(
        db,
        agent=agent,
        subject_type=subject_type,
        subject_source=subject_source,
        status=status,
        tier=tier,
    )
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0
