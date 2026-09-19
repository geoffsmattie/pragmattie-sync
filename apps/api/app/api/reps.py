from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB
from app.models import Rep
from app.schemas import RepOut

router = APIRouter(prefix="/reps", tags=["reps"])


@router.get("", response_model=list[RepOut])
def list_reps(db: DB) -> list[Rep]:
    return list(db.scalars(select(Rep).order_by(Rep.name)))
