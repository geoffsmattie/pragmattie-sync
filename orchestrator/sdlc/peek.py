"""Read-only looks at the orchestrator's database, for quick checks without ad-hoc scripts.

Only ever SELECTs. Allowlisted in .claude/settings.json so these checks need no approval.

    python -m sdlc.peek decisions [AGENT] [SOURCE] [N]   # latest audit rows (default: all, all, 20)
    python -m sdlc.peek runs                             # the rebuild implementer's runs and costs
    python -m sdlc.peek counts                           # rows per agent and source
"""

import sys

from sqlalchemy import func, select

from sdlc.db import SessionLocal
from sdlc.tables import AgentDecision


def decisions(db, agent: str | None, source: str | None, limit: int) -> None:
    query = select(AgentDecision).order_by(AgentDecision.id.desc()).limit(limit)
    if agent and agent != "all":
        query = query.where(AgentDecision.agent == agent)
    if source and source != "all":
        query = query.where(AgentDecision.subject_source == source)
    for d in db.scalars(query):
        out = d.output or {}
        detail = out.get("verdict") or out.get("module") or out.get("cost_usd") or ""
        print(
            f"{d.id} {d.created_at:%Y-%m-%d %H:%M} {d.agent} {d.subject_source} "
            f"{d.subject_type}#{d.subject_id} {d.status} tier={d.tier} score={d.final_score} "
            f"model={d.model_id} {detail}"
        )


def runs(db) -> None:
    total = 0.0
    for d in db.scalars(
        select(AgentDecision).where(AgentDecision.agent == "implementer").order_by(AgentDecision.id)
    ):
        out = d.output or {}
        cost = float(out.get("cost_usd") or 0)
        total += cost
        print(
            f"{d.created_at:%Y-%m-%d %H:%M} issue #{d.subject_id} {out.get('action')} {d.status} "
            f"{d.model_id} {out.get('turns')} turns ${cost:.2f}"
        )
    print(f"total ${total:.2f}")


def counts(db) -> None:
    rows = db.execute(
        select(AgentDecision.agent, AgentDecision.subject_source, func.count())
        .group_by(AgentDecision.agent, AgentDecision.subject_source)
        .order_by(AgentDecision.agent)
    )
    for agent, source, n in rows:
        print(f"{agent:<16} {source:<10} {n}")


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else ""
    with SessionLocal() as db:
        if cmd == "decisions":
            limit = int(argv[3]) if len(argv) > 3 else 20
            decisions(
                db, argv[1] if len(argv) > 1 else None, argv[2] if len(argv) > 2 else None, limit
            )
        elif cmd == "runs":
            runs(db)
        elif cmd == "counts":
            counts(db)
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
