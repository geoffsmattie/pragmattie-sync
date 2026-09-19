from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import Base, get_db

DB = Annotated[Session, Depends(get_db)]
M = TypeVar("M", bound=Base)


def get_or_404(db: Session, model: type[M], obj_id: int) -> M:
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} {obj_id} not found")
    return obj


def ensure_rep(db: Session, rep_id: int | None) -> None:
    from app.models import Rep

    if rep_id is not None:
        get_or_404(db, Rep, rep_id)
