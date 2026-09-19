"""ORM models for the PragMattie Sync CRM."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Closed sets are stored as short strings (portable across MySQL, Postgres and SQLite)
# and validated in the API schemas.
LEAD_STATUSES = ("new", "working", "qualified", "disqualified", "converted")
LEAD_SOURCES = ("web", "referral", "event", "outbound", "partner")
STAGES = ("prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost")
OPEN_STAGES = STAGES[:4]
# Default win probability (%) per stage.
STAGE_PROBABILITY = {
    "prospecting": 10,
    "qualification": 25,
    "proposal": 50,
    "negotiation": 75,
    "closed_won": 100,
    "closed_lost": 0,
}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Rep(Base):
    """A salesperson who owns leads, accounts and opportunities."""

    __tablename__ = "reps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    region: Mapped[str] = mapped_column(String(50))
    quarterly_quota: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    industry: Mapped[str] = mapped_column(String(80))
    employee_count: Mapped[int] = mapped_column(Integer)
    annual_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    region: Mapped[str] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(200))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[Rep | None] = relationship()
    contacts: Mapped[list["Contact"]] = relationship(back_populates="account")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="account")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="contacts")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(200), index=True)
    company: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    converted_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[Rep | None] = relationship()


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stage: Mapped[str] = mapped_column(String(20), default="prospecting", index=True)
    probability: Mapped[int] = mapped_column(Integer, default=10)
    close_date: Mapped[date] = mapped_column(Date, index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="opportunities")
    owner: Mapped[Rep | None] = relationship()
