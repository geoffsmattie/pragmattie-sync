"""HTTP API for the orchestration dashboard (served on port 8001)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from sdlc import accuracy, audit, forecaster, metrics
from sdlc import board as board_module
from sdlc.calibration import calibrate
from sdlc.config import get_settings
from sdlc.db import get_db
from sdlc.tables import PullRequest
from sdlc.tiers import load_policy

settings = get_settings()
DB = Annotated[Session, Depends(get_db)]

app = FastAPI(title=settings.app_name, version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


@app.get("/api/v1/health")
def health(db: DB) -> dict:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # pragma: no cover
        database = "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": settings.app_name,
        "database": database,
        "github_repo": settings.github_repo or None,
    }


@app.get("/api/v1/signals/summary")
def summary(db: DB, days: int = Query(30, ge=7, le=180)) -> dict:
    return metrics.dora_summary(db, _now(), days)


@app.get("/api/v1/signals/sprints")
def sprints(db: DB) -> list[dict]:
    return metrics.sprint_velocity(db, _now().date())


@app.get("/api/v1/signals/cycle-time")
def cycle_time(
    db: DB,
    bucket: Literal["sprint", "week"] = "sprint",
    weeks: int = Query(26, ge=1, le=104),
) -> list[dict]:
    """PR cycle time per sprint (default) or per calendar week."""
    if bucket == "week":
        return metrics.pr_cycle_time(db, weeks, _now())
    return metrics.pr_cycle_time_by_sprint(db, _now())


@app.get("/api/v1/signals/ci")
def ci(db: DB, weeks: int = Query(26, ge=1, le=104)) -> dict:
    return metrics.ci_health(db, weeks, _now())


@app.get("/api/v1/signals/modules")
def modules(db: DB) -> list[dict]:
    return metrics.quality_by_module(db)


@app.get("/api/v1/signals/sources")
def sources(db: DB) -> dict:
    return metrics.sources(db)


@app.get("/api/v1/signals/board")
def board(
    db: DB,
    sprint: str | None = None,  # "current" (default client-side), "all", or a sprint name
    module: str | None = None,
    owner: str | None = None,
    source: Literal["synthetic", "github"] | None = None,
) -> dict:
    return board_module.serialize(
        board_module.build_board(
            db, now=_now(), sprint=sprint, module=module, owner=owner, source=source
        )
    )


@app.get("/api/v1/signals/calibration")
def calibration(db: DB) -> dict:
    """How well the risk score separates the merged PRs that caused incidents in this database's
    history: precision and recall at each tier threshold, and the blueprint's two bars. One
    history is a noisy judge; the bars are graded pooled with `sdlc.risk calibrate --generated`."""
    report = calibrate(db, load_policy())
    real = db.scalar(
        select(func.count())
        .select_from(PullRequest)
        .where(PullRequest.state == "merged", PullRequest.source == "github")
    )
    return {**report, "real_merged_prs": real}


@app.get("/api/v1/signals/accuracy")
def accuracy_trend(db: DB) -> dict:
    """How accurate the predictions have been over time: forecasts, risk, triage, test selector."""
    return accuracy.report(db)


@app.get("/api/v1/signals/forecast")
def forecast(db: DB) -> dict:
    """The forecaster agent's latest saved sprint and epic forecasts, and how their dates moved."""
    return forecaster.dashboard(db)


@app.get("/api/v1/signals/decisions")
def decisions(
    db: DB,
    agent: str | None = None,
    subject_type: Literal["pr", "issue", "sprint", "epic", "release"] | None = None,
    subject_source: Literal["synthetic", "github", "mixed"] | None = None,
    status: Literal["ok", "error", "rejected", "missed"] | None = None,
    tier: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """The audit trail, newest first: every agent run, what it decided, what it did about it."""
    filters = dict(
        agent=agent,
        subject_type=subject_type,
        subject_source=subject_source,
        status=status,
        tier=tier,
    )
    rows = audit.list_decisions(db, limit=limit, offset=offset, **filters)
    return {
        "total": audit.count_decisions(db, **filters),
        "limit": limit,
        "offset": offset,
        "decisions": [audit.serialize_decision(d) for d in rows],
    }
