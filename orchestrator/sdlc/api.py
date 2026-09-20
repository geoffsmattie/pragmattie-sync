"""HTTP API for the orchestration dashboard (served on port 8001)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from sdlc import metrics
from sdlc.config import get_settings
from sdlc.db import get_db

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
