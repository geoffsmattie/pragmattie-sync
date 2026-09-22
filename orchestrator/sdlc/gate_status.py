"""Persist a PR's current risk-gate state, so it can be read without a live GitHub call.

Called by sdlc/runner.py every time it computes a Gate (sdlc/agents/gate.py), on every poll of
every open PR. One row per PR, replaced in place — this is a read model, not a history.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.agents.gate import Gate
from sdlc.tables import GateStatus, PullRequest


def upsert(
    db: Session, pr: PullRequest, gate: Gate, *, tier: str, mode: str, now: datetime | None = None
) -> GateStatus:
    row = db.scalar(select(GateStatus).where(GateStatus.pull_request_id == pr.id))
    if row is None:
        row = GateStatus(pull_request_id=pr.id)
        db.add(row)
    row.tier = tier
    row.state = gate.state
    row.would_be = gate.would_be
    row.missing = list(gate.missing)
    row.description = gate.description
    row.mode = mode
    row.updated_at = now or datetime.now().replace(microsecond=0)
    db.flush()
    return row
