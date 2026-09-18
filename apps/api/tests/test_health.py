from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_ok_with_database():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["service"] == "SyncVista CRM API"
