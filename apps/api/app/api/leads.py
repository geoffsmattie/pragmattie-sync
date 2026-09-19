from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import DB, ensure_rep, get_or_404
from app.models import STAGE_PROBABILITY, Account, Contact, Lead, Opportunity
from app.schemas import (
    LeadConvert,
    LeadConvertResult,
    LeadCreate,
    LeadOut,
    LeadSource,
    LeadStatus,
    LeadUpdate,
    Page,
)

router = APIRouter(prefix="/leads", tags=["leads"])

SORTABLE = {"created_at", "score", "company", "last_name", "status"}


@router.get("", response_model=Page[LeadOut])
def list_leads(
    db: DB,
    q: str | None = None,
    status: list[LeadStatus] | None = Query(None),
    source: LeadSource | None = None,
    owner_id: int | None = None,
    sort: str = "-created_at",
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Lead)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Lead.first_name.ilike(like)
            | Lead.last_name.ilike(like)
            | Lead.company.ilike(like)
            | Lead.email.ilike(like)
        )
    if status:
        stmt = stmt.where(Lead.status.in_(status))
    if source:
        stmt = stmt.where(Lead.source == source)
    if owner_id:
        stmt = stmt.where(Lead.owner_id == owner_id)
    field = sort.lstrip("-")
    if field not in SORTABLE:
        raise HTTPException(400, f"sort must be one of {sorted(SORTABLE)}")
    column = getattr(Lead, field)
    order = column.desc() if sort.startswith("-") else column.asc()
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(order, Lead.id.desc()).limit(limit).offset(offset))
    return {"items": list(rows), "total": total}


@router.post("", response_model=LeadOut, status_code=201)
def create_lead(payload: LeadCreate, db: DB) -> Lead:
    ensure_rep(db, payload.owner_id)
    lead = Lead(**payload.model_dump(), status="new")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: DB) -> Lead:
    return get_or_404(db, Lead, lead_id)


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, payload: LeadUpdate, db: DB) -> Lead:
    lead = get_or_404(db, Lead, lead_id)
    if lead.status == "converted":
        raise HTTPException(409, "Converted leads cannot be edited")
    changes = payload.model_dump(exclude_unset=True)
    ensure_rep(db, changes.get("owner_id"))
    for field, value in changes.items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/{lead_id}/convert", response_model=LeadConvertResult)
def convert_lead(lead_id: int, payload: LeadConvert, db: DB) -> dict:
    """Create an account and contact from a qualified lead, plus an optional opportunity."""
    lead = get_or_404(db, Lead, lead_id)
    if lead.status == "converted":
        raise HTTPException(409, "Lead is already converted")
    if lead.status == "disqualified":
        raise HTTPException(409, "Disqualified leads cannot be converted")

    account = Account(
        name=lead.company,
        industry=payload.industry,
        employee_count=payload.employee_count,
        annual_revenue=payload.annual_revenue,
        region=payload.region,
        owner_id=lead.owner_id,
    )
    db.add(account)
    db.flush()
    contact = Contact(
        account_id=account.id,
        first_name=lead.first_name,
        last_name=lead.last_name,
        email=lead.email,
        title=lead.title,
    )
    db.add(contact)

    opportunity = None
    if payload.opportunity_amount:
        opportunity = Opportunity(
            account_id=account.id,
            name=payload.opportunity_name or f"{lead.company} - New business",
            amount=payload.opportunity_amount,
            stage="qualification",
            probability=STAGE_PROBABILITY["qualification"],
            close_date=payload.opportunity_close_date or date.today() + timedelta(days=60),
            owner_id=lead.owner_id,
        )
        db.add(opportunity)

    lead.status = "converted"
    lead.converted_account_id = account.id
    db.commit()
    db.refresh(lead)
    return {
        "lead": lead,
        "account_id": account.id,
        "contact_id": contact.id,
        "opportunity_id": opportunity.id if opportunity else None,
    }
