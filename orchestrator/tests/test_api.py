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
