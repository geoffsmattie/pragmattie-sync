"""The forecaster agent: keep a saved, explainable forecast for the current sprint and every epic.

It runs in the shared poll loop (sdlc/runner.py) and re-forecasts a sprint or an epic only when
something it depends on has changed since its last saved forecast: a new day (history moves on),
a story added, closed or re-estimated, or work starting on an item. Each saved forecast is one
`sdlc_forecasts` row (the history the dashboard draws "the date moved" from) and one audit row,
per the agent contract every agent follows.

Reports only: it reads the signal tables and writes those two tables, and never touches GitHub
or calls Claude, so it costs nothing to run. ORCHESTRATOR_MODE=off stops it like the others.

Usage (inside the orchestrator container, or locally with the same .env):
    python -m sdlc.forecaster once      # forecast whatever changed, then exit
    python -m sdlc.forecaster now       # save a fresh forecast of everything (trigger=manual)
"""

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from sdlc.audit import record_decision
from sdlc.db import SessionLocal
from sdlc.forecast import (
    RUNS,
    EpicForecast,
    SprintForecast,
    current_sprint,
    describe,
    describe_epic,
    epic_forecast,
    epic_names,
    sprint_forecast,
)
from sdlc.tables import AgentDecision, Forecast, Issue, PullRequest, Sprint

AGENT = "forecaster"
AGENT_VERSION = "v1"
SOURCE = "synthetic"  # the sprint the team works in lives in the simulated history


# --- what a forecast depends on ----------------------------------------------------------------


def _fingerprint(today: date, subject: list, rows: list) -> str:
    """A hash of the day, the subject and its rows (in a stable order, whatever the query's)."""
    ordered = sorted(json.dumps(r, default=str) for r in rows)
    body = json.dumps([today.isoformat(), subject, ordered], default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def sprint_inputs(db: Session, sprint: Sprint, today: date) -> str:
    """The day, and each open item with its points, module and when work on it started."""
    items = list(
        db.scalars(select(Issue).where(Issue.sprint_id == sprint.id, Issue.state == "open"))
    )
    started: dict[int, datetime] = {}
    for issue_id, opened in db.execute(
        select(PullRequest.issue_id, PullRequest.created_at).where(
            PullRequest.issue_id.in_([i.id for i in items])
        )
    ):
        started[issue_id] = min(opened, started.get(issue_id, opened))
    rows = [(i.id, i.estimate_points, i.module, started.get(i.id)) for i in items]
    return _fingerprint(today, [sprint.id, sprint.end_date], rows)


def epic_inputs(db: Session, epic: str, today: date) -> str:
    """The day, and each of the epic's open stories with its points and source."""
    rows = db.execute(
        select(Issue.id, Issue.estimate_points, Issue.source).where(
            Issue.epic == epic, Issue.state == "open"
        )
    ).all()
    return _fingerprint(today, [epic], [tuple(r) for r in rows])


def latest(db: Session, kind: str, subject: str) -> Forecast | None:
    return db.scalar(
        select(Forecast)
        .where(Forecast.kind == kind, Forecast.subject == subject)
        .order_by(Forecast.created_at.desc(), Forecast.id.desc())
        .limit(1)
    )


# --- saving ------------------------------------------------------------------------------------


def _save(
    db: Session,
    f: SprintForecast | EpicForecast,
    *,
    inputs_hash: str,
    trigger: str,
    now: datetime,
) -> Forecast:
    sprint = isinstance(f, SprintForecast)
    source = f.source if sprint else ("mixed" if f.remaining_real else "synthetic")
    row = Forecast(
        created_at=now,
        as_of=f.as_of,
        kind="sprint" if sprint else "epic",
        subject=f.sprint if sprint else f.epic,
        source=source,
        trigger=trigger,
        inputs_hash=inputs_hash,
        remaining_items=f.remaining_items,
        remaining_real=0 if sprint else f.remaining_real,
        remaining_points=f.remaining_points,
        end_date=f.end_date if sprint else None,
        p50=f.p50,
        p85=f.p85,
        on_time_probability=f.on_time_probability if sprint else None,
        throughput_mean=f.throughput_mean,
        history_days=f.history_days,
        runs=f.runs,
        seed=f.seed,
        at_risk=[_jsonable(asdict(r)) for r in f.at_risk] if sprint else None,
    )
    db.add(row)
    db.flush()
    record_decision(
        db,
        agent=AGENT,
        agent_version=AGENT_VERSION,
        subject_type=row.kind,
        subject_source=source,
        subject_id=row.id,
        trigger=trigger,
        now=now,
        head_sha=inputs_hash[:40],
        inputs_digest={
            "remaining_items": row.remaining_items,
            "remaining_points": row.remaining_points,
            "throughput_mean": row.throughput_mean,
            "history_days": row.history_days,
        },
        output={
            "subject": row.subject,
            "p50": _iso(row.p50),
            "p85": _iso(row.p85),
            "end_date": _iso(row.end_date),
            # The agent contract's confidence: for a sprint, the chance of finishing on time.
            "confidence": row.on_time_probability,
            "rationale": describe(f) if sprint else describe_epic(f),
            "runs": row.runs,
            "seed": row.seed,
        },
        action_taken={"saved_forecast": row.id},
        status="ok",
    )
    return row


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _jsonable(d: dict) -> dict:
    return {k: _iso(v) if isinstance(v, date) else v for k, v in d.items()}


# --- the agent ---------------------------------------------------------------------------------


class ForecastRunner:
    def __init__(self, mode: str, runs: int = RUNS):
        self.mode = mode
        self.runs = runs

    def poll_once(self, now: datetime | None = None, *, force: bool = False) -> dict:
        """Forecast each subject whose inputs changed; with `force`, all of them."""
        if self.mode == "off":
            return {"mode": "off"}
        now = (now or datetime.now()).replace(microsecond=0)
        today = now.date()
        summary = {"mode": self.mode, "assessed": 0, "unchanged": 0}
        with SessionLocal() as db:
            subjects = []
            sprint = current_sprint(db, today, SOURCE)
            if sprint:
                subjects.append(("sprint", sprint.name, sprint_inputs(db, sprint, today), sprint))
            for name in epic_names(db):
                subjects.append(("epic", name, epic_inputs(db, name, today), None))

            for kind, subject, inputs_hash, sprint_row in subjects:
                last = latest(db, kind, subject)
                if not force and last and last.inputs_hash == inputs_hash:
                    summary["unchanged"] += 1
                    continue
                if kind == "sprint":
                    f = sprint_forecast(db, today, sprint=sprint_row, source=SOURCE, runs=self.runs)
                else:
                    f = epic_forecast(db, today, subject, runs=self.runs)
                if force:
                    trigger = "manual"
                elif last is None or last.as_of != today:
                    trigger = "schedule"  # the first forecast of the day
                else:
                    trigger = "change"
                _save(db, f, inputs_hash=inputs_hash, trigger=trigger, now=now)
                summary["assessed"] += 1
            db.commit()
        return summary


def moved(db: Session, kind: str, subject: str) -> dict | None:
    """The latest forecast and how its dates moved against the one before, for the dashboard."""
    rows = list(
        db.scalars(
            select(Forecast)
            .where(Forecast.kind == kind, Forecast.subject == subject)
            .order_by(Forecast.created_at.desc(), Forecast.id.desc())
            .limit(2)
        )
    )
    if not rows:
        return None
    now_row, before = rows[0], (rows[1] if len(rows) > 1 else None)

    def shift(attr: str) -> int | None:
        a, b = getattr(before, attr, None), getattr(now_row, attr)
        return (b - a).days if a and b else None

    return {
        "latest": now_row,
        "previous": before,
        "p50_days": shift("p50"),
        "p85_days": shift("p85"),
    }


TRAIL = 30  # past forecasts per subject for the dashboard's "how the date has moved" trail


def serialize(row: Forecast) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "as_of": _iso(row.as_of),
        "kind": row.kind,
        "subject": row.subject,
        "source": row.source,
        "trigger": row.trigger,
        "remaining_items": row.remaining_items,
        "remaining_real": row.remaining_real,
        "remaining_points": row.remaining_points,
        "end_date": _iso(row.end_date),
        "p50": _iso(row.p50),
        "p85": _iso(row.p85),
        "on_time_probability": row.on_time_probability,
        "throughput_mean": row.throughput_mean,
        "history_days": row.history_days,
        "runs": row.runs,
        "at_risk": row.at_risk or [],
    }


def dashboard(db: Session) -> dict:
    """The latest saved forecast of the current sprint and of every epic, each with how its dates
    moved since the forecast before and a short trail of past P50/P85s. Read-only: saving is the
    forecaster's job, so nothing here runs a simulation."""

    def entry(kind: str, subject: str) -> dict:
        rows = list(
            db.scalars(
                select(Forecast)
                .where(Forecast.kind == kind, Forecast.subject == subject)
                .order_by(Forecast.created_at.desc(), Forecast.id.desc())
                .limit(TRAIL)
            )
        )
        shift = moved(db, kind, subject)
        previous = shift["previous"]
        return {
            **serialize(rows[0]),
            "moved": {
                "p50_days": shift["p50_days"],
                "p85_days": shift["p85_days"],
                "previous_p50": _iso(previous.p50) if previous else None,
                "previous_p85": _iso(previous.p85) if previous else None,
                "previous_at": previous.created_at.isoformat() if previous else None,
            },
            "trail": [
                {"at": r.created_at.isoformat(), "p50": _iso(r.p50), "p85": _iso(r.p85)}
                for r in reversed(rows)
            ],
        }

    newest_sprint = db.scalar(
        select(Forecast.subject)
        .where(Forecast.kind == "sprint")
        .order_by(Forecast.created_at.desc(), Forecast.id.desc())
        .limit(1)
    )
    epics = sorted(db.scalars(select(Forecast.subject).where(Forecast.kind == "epic").distinct()))
    sprint = entry("sprint", newest_sprint) if newest_sprint else None
    if sprint:
        sprint["proposal"] = _proposal(db, newest_sprint, sprint["id"])
    return {
        "sprint": sprint,
        "epics": [entry("epic", name) for name in epics],
        "saved": db.scalar(select(func.count()).select_from(Forecast)),
    }


def _proposal(db: Session, sprint_name: str, latest_forecast_id: int) -> dict | None:
    """The planner's newest draft for this sprint, if any, and whether the forecast has moved on
    since it was drafted (then it's shown as out of date, not hidden)."""
    from sdlc.plan_runner import latest_proposal  # the planner builds on this module

    d = latest_proposal(db, sprint_name)
    if d is None:
        return None
    return {
        "decision_id": d.id,
        "created_at": d.created_at.isoformat(),
        "status": d.status,
        "error": d.error,
        "model": d.model_id,
        "input_tokens": d.input_tokens,
        "output_tokens": d.output_tokens,
        "current": d.subject_id == latest_forecast_id,
        **{
            k: v
            for k, v in (d.output or {}).items()
            if k not in ("request_id", "cache_read_tokens")
        },
    }


def reset(db: Session) -> None:
    """Forget every saved forecast and its audit rows (the history they describe is regenerated)."""
    db.execute(delete(AgentDecision).where(AgentDecision.agent.in_([AGENT, "planner"])))
    db.execute(delete(Forecast))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the forecaster agent.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("once", help="forecast whatever changed, then exit")
    commands.add_parser("now", help="save a fresh forecast of everything")
    args = parser.parse_args(argv)

    from sdlc.config import get_settings

    runner = ForecastRunner(get_settings().orchestrator_mode)
    print(runner.poll_once(force=args.command == "now"))


if __name__ == "__main__":
    main()
