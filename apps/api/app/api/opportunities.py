from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DB, ensure_rep, get_or_404
from app.models import STAGE_PROBABILITY, Account, Opportunity
from app.schemas import OpportunityCreate, OpportunityOut, OpportunityUpdate, Page, Stage

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=Page[OpportunityOut])
def list_opportunities(
    db: DB,
    stage: list[Stage] | None = Query(None),
    owner_id: int | None = None,
    account_id: int | None = None,
    close_from: date | None = None,
    close_to: date | None = None,
    q: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Opportunity)
    if stage:
        stmt = stmt.where(Opportunity.stage.in_(stage))
    if owner_id:
        stmt = stmt.where(Opportunity.owner_id == owner_id)
    if account_id:
        stmt = stmt.where(Opportunity.account_id == account_id)
    if close_from:
        stmt = stmt.where(Opportunity.close_date >= close_from)
    if close_to:
        stmt = stmt.where(Opportunity.close_date <= close_to)
    if q:
        stmt = stmt.where(Opportunity.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(Opportunity.close_date, Opportunity.id).limit(limit).offset(offset)
    )
    return {"items": list(rows), "total": total}


@router.post("", response_model=OpportunityOut, status_code=201)
def create_opportunity(payload: OpportunityCreate, db: DB) -> Opportunity:
    get_or_404(db, Account, payload.account_id)
    ensure_rep(db, payload.owner_id)
    data = payload.model_dump()
    if data["probability"] is None:
        data["probability"] = STAGE_PROBABILITY[data["stage"]]
    opp = Opportunity(**data)
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


@router.get("/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(opportunity_id: int, db: DB) -> Opportunity:
    return get_or_404(db, Opportunity, opportunity_id)


@router.patch("/{opportunity_id}", response_model=OpportunityOut)
def update_opportunity(opportunity_id: int, payload: OpportunityUpdate, db: DB) -> Opportunity:
    opp = get_or_404(db, Opportunity, opportunity_id)
    changes = payload.model_dump(exclude_unset=True)
    ensure_rep(db, changes.get("owner_id"))
    # Moving stage resets probability to the stage default unless one is given.
    if "stage" in changes and "probability" not in changes:
        changes["probability"] = STAGE_PROBABILITY[changes["stage"]]
    for field, value in changes.items():
        setattr(opp, field, value)
    db.commit()
    db.refresh(opp)
    return opp
