from datetime import date
from decimal import Decimal

import pytest

from app.forecast import Quarter, compute_forecast
from app.models import Opportunity, Rep


def opp(stage, amount, close, probability, owner_id=1):
    return Opportunity(
        stage=stage,
        amount=Decimal(amount),
        close_date=close,
        probability=probability,
        owner_id=owner_id,
    )


def test_quarter_parsing_and_bounds():
    q = Quarter.parse("2026-Q3")
    assert (q.start, q.end) == (date(2026, 7, 1), date(2026, 9, 30))
    assert Quarter.containing(date(2026, 12, 31)).label == "2026-Q4"
    assert Quarter.parse("2026-Q4").end == date(2026, 12, 31)
    with pytest.raises(ValueError):
        Quarter.parse("2026-Q5")


def test_forecast_categories():
    q = Quarter.parse("2026-Q3")
    rep = Rep(id=1, name="Avery", quarterly_quota=Decimal(100_000))
    opps = [
        opp("closed_won", 30_000, date(2026, 7, 10), 100),
        opp("negotiation", 20_000, date(2026, 8, 5), 75),
        opp("proposal", 10_000, date(2026, 9, 12), 50),
        opp("prospecting", 40_000, date(2026, 9, 20), 10),
        opp("closed_lost", 99_000, date(2026, 9, 1), 0),
        opp("proposal", 50_000, date(2026, 10, 2), 50),  # next quarter: excluded
    ]
    f = compute_forecast(opps, [rep], q)
    assert f["won"] == 30_000
    assert f["commit"] == 50_000  # won + negotiation
    assert f["best_case"] == 60_000  # commit + proposal
    assert f["pipeline"] == 70_000  # open deals only
    assert f["weighted"] == Decimal("54000.00")  # 30k + 15k + 5k + 4k
    assert [m["month"] for m in f["by_month"]] == ["2026-07", "2026-08", "2026-09"]
    assert f["by_rep"][0]["attainment_pct"] == 30.0
    assert {s["stage"]: s["count"] for s in f["by_stage"]}["proposal"] == 1


def test_forecast_endpoint_validates_quarter(client):
    assert client.get("/api/v1/forecast", params={"quarter": "Q3"}).status_code == 400
    assert client.get("/api/v1/forecast", params={"quarter": "2026-Q3"}).json()["won"] == "0"
