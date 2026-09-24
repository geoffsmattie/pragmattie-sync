from fastapi.testclient import TestClient

from sdlc.api import app

client = TestClient(app)


def test_endpoints_serve_synthetic_history(history):
    assert client.get("/api/v1/health").json()["database"] == "ok"
    assert len(client.get("/api/v1/signals/sprints").json()) == 13
    assert client.get("/api/v1/signals/sources").json()["pull_requests"]["synthetic"] > 0
    summary = client.get("/api/v1/signals/summary", params={"days": 90}).json()
    assert summary["current"]["deployments"] >= 0
    assert client.get("/api/v1/signals/modules").status_code == 200
    assert "by_suite" in client.get("/api/v1/signals/ci").json()
    assert client.get("/api/v1/signals/summary", params={"days": 1}).status_code == 422


def test_cycle_time_by_sprint_and_week(history):
    by_sprint = client.get("/api/v1/signals/cycle-time").json()
    assert len(by_sprint) == 13
    assert all(row["median_hours"] <= row["p85_hours"] for row in by_sprint if row["merged"])
    by_week = client.get("/api/v1/signals/cycle-time", params={"bucket": "week"}).json()
    assert by_week and "week" in by_week[0]


def test_forecast_endpoint_serves_saved_forecasts_and_how_they_moved(db, history):
    from sdlc.forecaster import ForecastRunner
    from sdlc.tables import Issue
    from tests.conftest import NOW

    assert client.get("/api/v1/signals/forecast").json() == {
        "sprint": None,
        "epics": [],
        "saved": 0,
    }
    agent = ForecastRunner("shadow", runs=300)
    agent.poll_once(NOW)
    for n in range(3):
        db.add(
            Issue(
                source="github",
                external_id=f"issue-{800 + n}",
                number=800 + n,
                title="Live story",
                state="open",
                created_at=NOW,
                epic="Salesforce import",
                estimate_points=3,
            )
        )
    db.commit()
    agent.poll_once(NOW)

    body = client.get("/api/v1/signals/forecast").json()
    assert body["sprint"]["subject"] == "Sprint 13" and body["sprint"]["moved"]["p50_days"] is None
    assert len(body["epics"]) == 4 and body["saved"] == 6
    epic = next(e for e in body["epics"] if e["subject"] == "Salesforce import")
    assert epic["source"] == "mixed" and epic["moved"]["p50_days"] > 0
    assert [t["p50"] for t in epic["trail"]] == [epic["moved"]["previous_p50"], epic["p50"]]

    by_kind = client.get("/api/v1/signals/decisions", params={"subject_type": "epic"}).json()
    assert by_kind["total"] == 5  # four scheduled, one after the live stories
    assert (
        client.get("/api/v1/signals/decisions", params={"subject_source": "mixed"}).status_code
        == 200
    )


def test_calibration_endpoint_reports_thresholds_and_bars(history):
    body = client.get("/api/v1/signals/calibration").json()
    assert body["merged_prs"] > 300 and body["incident_prs"] > 0
    assert set(body["thresholds"]) == {"T1", "T2", "T3"}
    t1 = body["thresholds"]["T1"]
    assert 0 <= t1["precision"] <= 1 and 0 <= t1["recall"] <= 1
    assert set(body["bars"]) == {"t0_has_no_incidents", "top_decile_captures_majority"}
    assert body["real_merged_prs"] == 0


def test_the_decision_log_filters_by_every_status_the_agents_write(db):
    from sdlc.audit import record_decision

    for status in ("ok", "error", "rejected", "missed"):
        record_decision(
            db,
            agent="test_selector",
            agent_version="v1",
            subject_type="pr",
            subject_source="github",
            subject_id=1,
            trigger="poll",
            head_sha=status,
            status=status,
        )
    db.commit()
    for status in ("ok", "error", "rejected", "missed"):
        body = client.get("/api/v1/signals/decisions", params={"status": status}).json()
        assert [d["status"] for d in body["decisions"]] == [status]
    assert client.get("/api/v1/signals/decisions", params={"status": "nope"}).status_code == 422
