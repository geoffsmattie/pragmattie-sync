"""Revenue forecast math, kept separate from the API so it is easy to test and explain.

Forecast categories (the usual sales-ops definitions) for deals closing in the quarter:
  won        closed_won
  commit     won + negotiation
  best_case  commit + proposal
  pipeline   every open deal (prospecting through negotiation)
  weighted   won + sum(open amount x probability)
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models import OPEN_STAGES, Opportunity, Rep

ZERO = Decimal(0)
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


@dataclass(frozen=True)
class Quarter:
    year: int
    q: int

    @classmethod
    def parse(cls, text: str) -> "Quarter":
        match = QUARTER_RE.match(text)
        if not match:
            raise ValueError("quarter must look like 2026-Q3")
        return cls(int(match[1]), int(match[2]))

    @classmethod
    def containing(cls, day: date) -> "Quarter":
        return cls(day.year, (day.month - 1) // 3 + 1)

    @property
    def label(self) -> str:
        return f"{self.year}-Q{self.q}"

    @property
    def months(self) -> list[tuple[int, int]]:
        first = (self.q - 1) * 3 + 1
        return [(self.year, m) for m in range(first, first + 3)]

    @property
    def start(self) -> date:
        return date(self.year, self.months[0][1], 1)

    @property
    def end(self) -> date:
        y, m = self.months[-1]
        nxt = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)


def _buckets(opps: list[Opportunity]) -> dict[str, Decimal]:
    won = sum((o.amount for o in opps if o.stage == "closed_won"), ZERO)
    negotiation = sum((o.amount for o in opps if o.stage == "negotiation"), ZERO)
    proposal = sum((o.amount for o in opps if o.stage == "proposal"), ZERO)
    open_opps = [o for o in opps if o.stage in OPEN_STAGES]
    pipeline = sum((o.amount for o in open_opps), ZERO)
    weighted = won + sum((o.amount * o.probability / Decimal(100) for o in open_opps), ZERO)
    commit = won + negotiation
    return {
        "won": won,
        "commit": commit,
        "best_case": commit + proposal,
        "pipeline": pipeline,
        "weighted": weighted.quantize(Decimal("0.01")),
    }


def compute_forecast(opps: list[Opportunity], reps: list[Rep], quarter: Quarter) -> dict:
    in_quarter = [o for o in opps if quarter.start <= o.close_date <= quarter.end]
    totals = _buckets(in_quarter)

    by_month = []
    for year, month in quarter.months:
        month_opps = [
            o for o in in_quarter if (o.close_date.year, o.close_date.month) == (year, month)
        ]
        b = _buckets(month_opps)
        by_month.append(
            {
                "month": f"{year}-{month:02d}",
                "won": b["won"],
                "commit": b["commit"],
                "best_case": b["best_case"],
                "weighted": b["weighted"],
            }
        )

    per_rep: dict[int, list[Opportunity]] = defaultdict(list)
    for o in in_quarter:
        if o.owner_id is not None:
            per_rep[o.owner_id].append(o)
    by_rep = []
    for rep in reps:
        b = _buckets(per_rep.get(rep.id, []))
        quota = rep.quarterly_quota or ZERO
        attainment = float(b["won"] / quota * 100) if quota else 0.0
        by_rep.append(
            {
                "rep": {"id": rep.id, "name": rep.name},
                "quota": quota,
                "won": b["won"],
                "commit": b["commit"],
                "weighted": b["weighted"],
                "attainment_pct": round(attainment, 1),
            }
        )
    by_rep.sort(key=lambda r: r["weighted"], reverse=True)

    by_stage = []
    for stage in OPEN_STAGES:
        stage_opps = [o for o in in_quarter if o.stage == stage]
        by_stage.append(
            {
                "stage": stage,
                "count": len(stage_opps),
                "amount": sum((o.amount for o in stage_opps), ZERO),
            }
        )

    return {
        "quarter": quarter.label,
        "start": quarter.start,
        "end": quarter.end,
        "quota": sum((r.quarterly_quota or ZERO for r in reps), ZERO),
        **totals,
        "by_month": by_month,
        "by_rep": by_rep,
        "by_stage": by_stage,
    }
