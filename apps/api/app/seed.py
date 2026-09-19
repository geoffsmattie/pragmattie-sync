"""Demo CRM data for PragMattie Sync. Every company and person here is invented.

Usage:
    python -m app.seed              # add demo data (refuses if data already exists)
    python -m app.seed --if-empty   # add demo data only when the database is empty
    python -m app.seed --reset      # wipe CRM tables, then add demo data

Data is generated from a fixed random seed, with dates relative to today, so the
pipeline and forecast always look current.
"""

import argparse
import random
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.forecast import Quarter
from app.models import STAGE_PROBABILITY, Account, Contact, Lead, Opportunity, Rep

SEED = 42

REPS = [
    ("Avery Collins", "North America East", 420_000),
    ("Jordan Reyes", "North America West", 450_000),
    ("Morgan Blake", "North America Central", 380_000),
    ("Riley Chen", "EMEA", 400_000),
    ("Casey Okafor", "EMEA", 360_000),
    ("Taylor Brooks", "APAC", 320_000),
]

NAME_A = [
    "Northbeam",
    "Cobalt Ridge",
    "Silverline",
    "Brightwater",
    "Ironleaf",
    "Bluepeak",
    "Clearpath",
    "Redwood Arc",
    "Granite Bay",
    "Summit Row",
    "Harborlight",
    "Keystone Vale",
    "Lumen Field",
    "Maple Crest",
    "Oakhaven",
    "Pinecone",
    "Quarry Hill",
    "Riverstone",
    "Stonebridge",
    "Tidewell",
    "Upland",
    "Westmark",
    "Amberfield",
    "Copperleaf",
    "Driftwood",
    "Evergreen Loop",
    "Foxglove",
    "Goldcrest",
    "Hollowpine",
    "Juniper Gate",
]
NAME_B = [
    "Logistics",
    "Health",
    "Analytics",
    "Manufacturing",
    "Software",
    "Financial",
    "Energy",
    "Retail Group",
    "Labs",
    "Systems",
    "Partners",
    "Networks",
]
INDUSTRY_FOR = {
    "Logistics": "Transportation",
    "Health": "Healthcare",
    "Analytics": "Technology",
    "Manufacturing": "Manufacturing",
    "Software": "Technology",
    "Financial": "Financial Services",
    "Energy": "Energy",
    "Retail Group": "Retail",
    "Labs": "Life Sciences",
    "Systems": "Technology",
    "Partners": "Professional Services",
    "Networks": "Telecommunications",
}
FIRST = [
    "Alex",
    "Blair",
    "Cameron",
    "Dana",
    "Elliot",
    "Frankie",
    "Gray",
    "Harper",
    "Indy",
    "Jesse",
    "Kai",
    "Logan",
    "Marley",
    "Noel",
    "Oakley",
    "Parker",
    "Quinn",
    "Reese",
    "Sage",
    "Tatum",
    "Val",
    "Wren",
    "Emery",
    "Rowan",
    "Sloane",
    "Ari",
    "Devon",
    "Hayden",
    "Lane",
    "Micah",
]
LAST = [
    "Abbott",
    "Barnes",
    "Castillo",
    "Dawson",
    "Ellis",
    "Foster",
    "Garner",
    "Hughes",
    "Ingram",
    "Jennings",
    "Keller",
    "Lawson",
    "Mercer",
    "Nolan",
    "Ortega",
    "Porter",
    "Quincy",
    "Ramsey",
    "Sutton",
    "Tran",
    "Underwood",
    "Vance",
    "Whitaker",
    "Young",
    "Zimmer",
    "Patel",
    "Kim",
    "Novak",
    "Silva",
    "Haddad",
]
TITLES = [
    "VP of Sales",
    "Director of Revenue Operations",
    "Head of Sales",
    "Chief Revenue Officer",
    "Sales Operations Manager",
    "VP of Marketing",
    "Director of IT",
    "COO",
    "CFO",
    "Business Systems Analyst",
]
DEAL_TYPES = ["New business", "Expansion", "Renewal", "Add-on seats", "Platform upgrade"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _email(first: str, last: str, company: str) -> str:
    # .example is a reserved domain, so these can never be real addresses.
    return f"{first}.{last}@{_slug(company)}.example".lower()


def _pick_stage(rng: random.Random, close: date, today: date) -> str:
    if close < today:
        return rng.choices(["closed_won", "closed_lost"], weights=[45, 55])[0]
    days_out = (close - today).days
    if days_out <= 30:
        weights = [5, 15, 35, 45]
    elif days_out <= 75:
        weights = [20, 35, 30, 15]
    else:
        weights = [45, 35, 15, 5]
    return rng.choices(["prospecting", "qualification", "proposal", "negotiation"], weights)[0]


def build(db: Session, today: date | None = None) -> dict[str, int]:
    rng = random.Random(SEED)
    today = today or date.today()
    now = datetime.combine(today, datetime.min.time())

    reps = [
        Rep(
            name=name,
            email=_email(*name.split(), "PragMattie Sync"),
            region=region,
            quarterly_quota=Decimal(quota),
        )
        for name, region, quota in REPS
    ]
    db.add_all(reps)
    db.flush()

    names = rng.sample([f"{a} {b}" for a in NAME_A for b in NAME_B], 60)
    accounts = []
    for name in names:
        employees = rng.choice([40, 85, 150, 320, 600, 1200, 2500, 5000])
        accounts.append(
            Account(
                name=name,
                industry=INDUSTRY_FOR[next(b for b in NAME_B if name.endswith(b))],
                employee_count=employees,
                annual_revenue=Decimal(employees * rng.randint(120, 260) * 1000),
                region=rng.choice([r[1] for r in REPS]),
                website=f"https://{_slug(name)}.example",
                owner_id=rng.choice(reps).id,
                created_at=now - timedelta(days=rng.randint(120, 720)),
            )
        )
    db.add_all(accounts)
    db.flush()

    contacts = []
    for account in accounts:
        for _ in range(rng.randint(1, 4)):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            contacts.append(
                Contact(
                    account_id=account.id,
                    first_name=first,
                    last_name=last,
                    email=_email(first, last, account.name),
                    title=rng.choice(TITLES),
                    phone=f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
                    created_at=account.created_at + timedelta(days=rng.randint(1, 60)),
                )
            )
    db.add_all(contacts)

    # Opportunities are generated per rep against quota, so the forecast tells a
    # believable story: last two quarters closed, this quarter part-won with deals
    # still in play, next quarter mostly early-stage pipeline.
    quarter = Quarter.containing(today)
    q_days = (quarter.end - quarter.start).days + 1
    elapsed = max(0.0, min(1.0, (today - quarter.start).days / q_days))
    prev1 = Quarter.containing(quarter.start - timedelta(days=1))
    prev2 = Quarter.containing(prev1.start - timedelta(days=1))
    nxt = Quarter.containing(quarter.end + timedelta(days=1))
    by_owner = {rep.id: [a for a in accounts if a.owner_id == rep.id] or accounts for rep in reps}
    opportunities = []

    def add_deals(rep: Rep, total: float, first: date, last: date, stage_fn) -> None:
        span = max(0, (last - first).days)
        added = 0.0
        while added < total:
            amount = Decimal(rng.choice([12, 18, 25, 36, 48, 60, 75, 90, 120]) * 1000)
            amount += Decimal(rng.randint(0, 8) * 500)
            close = first + timedelta(days=rng.randint(0, span))
            stage = stage_fn(close)
            account = rng.choice(by_owner[rep.id])
            opportunities.append(
                Opportunity(
                    account_id=account.id,
                    name=f"{account.name} - {rng.choice(DEAL_TYPES)}",
                    amount=amount,
                    stage=stage,
                    probability=STAGE_PROBABILITY[stage],
                    close_date=close,
                    owner_id=rep.id,
                    created_at=datetime.combine(close, datetime.min.time())
                    - timedelta(days=rng.randint(30, 120)),
                )
            )
            added += float(amount)

    def won(_close: date) -> str:
        return "closed_won"

    def lost(_close: date) -> str:
        return "closed_lost"

    def open_stage(close: date) -> str:
        return _pick_stage(rng, max(close, today + timedelta(days=1)), today)

    for rep in reps:
        quota = float(rep.quarterly_quota)
        strength = rng.uniform(0.55, 1.0)  # how well this rep is tracking this quarter
        for past in (prev2, prev1):
            add_deals(rep, quota * rng.uniform(0.8, 1.15), past.start, past.end, won)
            add_deals(rep, quota * rng.uniform(0.3, 0.6), past.start, past.end, lost)
        if elapsed > 0:
            yesterday = today - timedelta(days=1)
            add_deals(rep, quota * elapsed * strength, quarter.start, yesterday, won)
            add_deals(rep, quota * elapsed * 0.3, quarter.start, yesterday, lost)
        remaining = quota * max(0.25, 1.15 - elapsed * strength)
        add_deals(rep, remaining, today + timedelta(days=1), quarter.end, open_stage)
        add_deals(rep, quota * rng.uniform(1.8, 2.6), nxt.start, nxt.end, open_stage)

    db.add_all(opportunities)

    # Leads: the last 90 days of inbound and outbound interest.
    statuses = ["new", "working", "qualified", "disqualified"]
    leads = []
    used = set(names)
    for _ in range(220):
        company = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)}"
        if company in used and rng.random() < 0.8:
            company = f"{rng.choice(NAME_A)} {rng.choice(['Group', 'Co', 'Holdings', 'Works'])}"
        first, last = rng.choice(FIRST), rng.choice(LAST)
        age = rng.randint(0, 90)
        # Older leads are more likely to have moved on from "new".
        weights = [60, 25, 10, 5] if age < 10 else [15, 35, 30, 20]
        status = rng.choices(statuses, weights)[0]
        base = {"new": 35, "working": 50, "qualified": 75, "disqualified": 20}[status]
        leads.append(
            Lead(
                first_name=first,
                last_name=last,
                email=_email(first, last, company),
                company=company,
                title=rng.choice(TITLES),
                source=rng.choices(
                    ["web", "referral", "event", "outbound", "partner"], [40, 15, 15, 20, 10]
                )[0],
                status=status,
                score=max(1, min(99, base + rng.randint(-20, 20))),
                owner_id=rng.choice(reps).id,
                created_at=now - timedelta(days=age, hours=rng.randint(0, 23)),
            )
        )
    db.add_all(leads)
    db.commit()
    return {
        "reps": len(reps),
        "accounts": len(accounts),
        "contacts": len(contacts),
        "opportunities": len(opportunities),
        "leads": len(leads),
    }


def reset(db: Session) -> None:
    for model in (Lead, Opportunity, Contact, Account, Rep):
        db.execute(delete(model))
        if db.bind.dialect.name == "mysql":
            # Restart IDs at 1 so links like /accounts/1 stay stable across resets.
            db.execute(text(f"ALTER TABLE {model.__tablename__} AUTO_INCREMENT = 1"))
    db.commit()


def is_empty(db: Session) -> bool:
    return not db.scalar(select(func.count()).select_from(Rep))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--if-empty", action="store_true", help="skip if data already exists")
    parser.add_argument("--reset", action="store_true", help="delete CRM data first")
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.reset:
            reset(db)
        elif not is_empty(db):
            if args.if_empty:
                print("Demo data already present; skipping seed.")
                return
            raise SystemExit("Database already has data. Use --reset to replace it.")
        counts = build(db)
        print("Seeded demo data: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
