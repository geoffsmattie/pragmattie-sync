"""Request and response shapes for the API (Pydantic models)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

LeadStatus = Literal["new", "working", "qualified", "disqualified", "converted"]
LeadSource = Literal["web", "referral", "event", "outbound", "partner"]
Stage = Literal[
    "prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost"
]

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


# --- Reps -----------------------------------------------------------------------------


class RepOut(ORM):
    id: int
    name: str
    email: str
    region: str
    quarterly_quota: Decimal


class RepRef(ORM):
    id: int
    name: str


# --- Accounts & contacts --------------------------------------------------------------


class AccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str = Field(min_length=1, max_length=80)
    employee_count: int = Field(ge=1)
    annual_revenue: Decimal = Field(ge=0)
    region: str = Field(min_length=1, max_length=50)
    website: str | None = None
    owner_id: int | None = None


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = None
    employee_count: int | None = Field(default=None, ge=1)
    annual_revenue: Decimal | None = Field(default=None, ge=0)
    region: str | None = None
    website: str | None = None
    owner_id: int | None = None


class AccountOut(ORM, AccountBase):
    id: int
    created_at: datetime
    owner: RepRef | None = None
    open_pipeline: Decimal = Decimal(0)
    contact_count: int = 0


class ContactBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    title: str | None = None
    phone: str | None = None


class ContactCreate(ContactBase):
    account_id: int


class ContactOut(ORM, ContactBase):
    id: int
    account_id: int
    created_at: datetime


# --- Opportunities --------------------------------------------------------------------


class OpportunityCreate(BaseModel):
    account_id: int
    name: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0)
    stage: Stage = "prospecting"
    probability: int | None = Field(default=None, ge=0, le=100)
    close_date: date
    owner_id: int | None = None


class OpportunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0)
    stage: Stage | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    close_date: date | None = None
    owner_id: int | None = None


class AccountRef(ORM):
    id: int
    name: str


class OpportunityOut(ORM):
    id: int
    account_id: int
    account: AccountRef
    name: str
    amount: Decimal
    stage: Stage
    probability: int
    close_date: date
    owner: RepRef | None = None
    created_at: datetime


class AccountDetail(AccountOut):
    contacts: list[ContactOut]
    opportunities: list[OpportunityOut]


# --- Leads ----------------------------------------------------------------------------


class LeadBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    company: str = Field(min_length=1, max_length=200)
    title: str | None = None
    source: LeadSource = "web"
    owner_id: int | None = None


class LeadCreate(LeadBase):
    score: int = Field(default=0, ge=0, le=100)


class LeadUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    email: EmailStr | None = None
    company: str | None = None
    title: str | None = None
    source: LeadSource | None = None
    status: Literal["new", "working", "qualified", "disqualified"] | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    owner_id: int | None = None


class LeadOut(ORM, LeadBase):
    id: int
    status: LeadStatus
    score: int
    owner: RepRef | None = None
    converted_account_id: int | None = None
    created_at: datetime


class LeadConvert(BaseModel):
    """Turn a lead into an account + contact, optionally with a first opportunity."""

    industry: str = "Unknown"
    employee_count: int = Field(default=50, ge=1)
    annual_revenue: Decimal = Field(default=Decimal(0), ge=0)
    region: str = "North America"
    opportunity_name: str | None = None
    opportunity_amount: Decimal | None = Field(default=None, gt=0)
    opportunity_close_date: date | None = None


class LeadConvertResult(BaseModel):
    lead: LeadOut
    account_id: int
    contact_id: int
    opportunity_id: int | None


# --- Forecast -------------------------------------------------------------------------


class StageSummary(BaseModel):
    stage: Stage
    count: int
    amount: Decimal


class MonthForecast(BaseModel):
    month: str  # YYYY-MM
    won: Decimal
    commit: Decimal
    best_case: Decimal
    weighted: Decimal


class RepForecast(BaseModel):
    rep: RepRef
    quota: Decimal
    won: Decimal
    commit: Decimal
    weighted: Decimal
    attainment_pct: float


class Forecast(BaseModel):
    quarter: str
    start: date
    end: date
    quota: Decimal
    won: Decimal
    commit: Decimal
    best_case: Decimal
    pipeline: Decimal
    weighted: Decimal
    by_month: list[MonthForecast]
    by_rep: list[RepForecast]
    by_stage: list[StageSummary]
