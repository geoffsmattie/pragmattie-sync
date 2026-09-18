from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> dict:
    """Liveness plus a database round-trip, used by Docker, CI and the web app."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # pragma: no cover - exercised only when the DB is down
        database = "unavailable"
    settings = get_settings()
    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": settings.app_name,
        "environment": settings.environment,
        "database": database,
    }
