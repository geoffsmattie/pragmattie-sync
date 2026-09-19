from datetime import date

from app.seed import build, is_empty, reset


def test_seed_builds_a_consistent_demo(db, client):
    assert is_empty(db)
    counts = build(db, today=date(2026, 9, 18))
    assert counts["reps"] == 6
    assert counts["accounts"] == 60
    assert counts["leads"] == 220
    assert counts["opportunities"] > 100

    f = client.get("/api/v1/forecast", params={"quarter": "2026-Q3"}).json()
    won, commit, best = (float(f[k]) for k in ("won", "commit", "best_case"))
    assert 0 < won <= commit <= best
    # The current quarter should be partly won, with deals still open.
    assert float(f["pipeline"]) > 0

    summary = client.get("/api/v1/summary").json()
    assert summary["open_leads"] > 0


def test_seed_is_repeatable(db):
    first = build(db, today=date(2026, 9, 18))
    reset(db)
    assert is_empty(db)
    assert build(db, today=date(2026, 9, 18)) == first
