from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DB, ensure_rep, get_or_404
from app.models import OPEN_STAGES, Account, Contact, Opportunity
from app.schemas import (
    AccountCreate,
    AccountDetail,
    AccountOut,
    AccountUpdate,
    ContactCreate,
    ContactOut,
    Page,
)

router = APIRouter(tags=["accounts"])


def _with_rollups(db: DB, accounts: list[Account]) -> list[AccountOut]:
    """Attach open pipeline and contact count to each account."""
    ids = [a.id for a in accounts]
    if not ids:
        return []
    pipeline = dict(
        db.execute(
            select(Opportunity.account_id, func.sum(Opportunity.amount))
            .where(Opportunity.account_id.in_(ids), Opportunity.stage.in_(OPEN_STAGES))
            .group_by(Opportunity.account_id)
        ).all()
    )
    contacts = dict(
        db.execute(
            select(Contact.account_id, func.count(Contact.id))
            .where(Contact.account_id.in_(ids))
            .group_by(Contact.account_id)
        ).all()
    )
    out = []
    for a in accounts:
        item = AccountOut.model_validate(a)
        item.open_pipeline = Decimal(pipeline.get(a.id) or 0)
        item.contact_count = contacts.get(a.id, 0)
        out.append(item)
    return out


@router.get("/accounts", response_model=Page[AccountOut])
def list_accounts(
    db: DB,
    q: str | None = None,
    industry: str | None = None,
    owner_id: int | None = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Account)
    if q:
        stmt = stmt.where(Account.name.ilike(f"%{q}%"))
    if industry:
        stmt = stmt.where(Account.industry == industry)
    if owner_id:
        stmt = stmt.where(Account.owner_id == owner_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(Account.name).limit(limit).offset(offset)))
    return {"items": _with_rollups(db, rows), "total": total}


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, db: DB) -> AccountOut:
    ensure_rep(db, payload.owner_id)
    account = Account(**payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return _with_rollups(db, [account])[0]


@router.get("/accounts/{account_id}", response_model=AccountDetail)
def get_account(account_id: int, db: DB) -> AccountDetail:
    account = get_or_404(db, Account, account_id)
    base = _with_rollups(db, [account])[0]
    return AccountDetail(
        **base.model_dump(),
        contacts=[ContactOut.model_validate(c) for c in account.contacts],
        opportunities=sorted(account.opportunities, key=lambda o: o.close_date),
    )


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: int, payload: AccountUpdate, db: DB) -> AccountOut:
    account = get_or_404(db, Account, account_id)
    changes = payload.model_dump(exclude_unset=True)
    ensure_rep(db, changes.get("owner_id"))
    for field, value in changes.items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return _with_rollups(db, [account])[0]


@router.get("/contacts", response_model=Page[ContactOut])
def list_contacts(
    db: DB,
    account_id: int | None = None,
    q: str | None = None,
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    stmt = select(Contact)
    if account_id:
        stmt = stmt.where(Contact.account_id == account_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Contact.first_name.ilike(like)
            | Contact.last_name.ilike(like)
            | Contact.email.ilike(like)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Contact.last_name).limit(limit).offset(offset))
    return {"items": list(rows), "total": total}


@router.post("/contacts", response_model=ContactOut, status_code=201)
def create_contact(payload: ContactCreate, db: DB) -> Contact:
    get_or_404(db, Account, payload.account_id)
    contact = Contact(**payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact
