from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import DB
from app.forecast import Quarter, compute_forecast
from app.models import OPEN_STAGES, Lead, Opportunity, Rep
from app.schemas import Forecast

router = APIRouter(tags=["forecast"])


@router.get("/forecast", response_model=Forecast)
def get_forecast(db: DB, quarter: str | None = None) -> dict:
    """Quarterly revenue forecast. `quarter` looks like 2026-Q3; defaults to the current one."""
    try:
        q = Quarter.parse(quarter) if quarter else Quarter.containing(date.today())
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    opps = list(
        db.scalars(
            select(Opportunity).where(
                Opportunity.close_date >= q.start, Opportunity.close_date <= q.end
            )
        )
    )
    reps = list(db.scalars(select(Rep).order_by(Rep.name)))
    return compute_forecast(opps, reps, q)


@router.get("/summary")
def get_summary(db: DB) -> dict:
    """Headline numbers for the home page."""
    lead_counts = dict(db.execute(select(Lead.status, func.count()).group_by(Lead.status)).all())
    open_pipeline = db.scalar(
        select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
            Opportunity.stage.in_(OPEN_STAGES)
        )
    )
    open_deals = db.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.stage.in_(OPEN_STAGES))
    )
    q = Quarter.containing(date.today())
    won_this_quarter = db.scalar(
        select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
            Opportunity.stage == "closed_won",
            Opportunity.close_date >= q.start,
            Opportunity.close_date <= q.end,
        )
    )
    return {
        "quarter": q.label,
        "leads_by_status": lead_counts,
        "open_leads": sum(
            v for k, v in lead_counts.items() if k in ("new", "working", "qualified")
        ),
        "open_pipeline": open_pipeline,
        "open_deals": open_deals,
        "won_this_quarter": won_this_quarter,
    }
