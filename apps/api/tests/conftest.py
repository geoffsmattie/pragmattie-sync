import os

# Tests run against a throwaway SQLite file so they need no MySQL server.
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Rep  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def rep(db):
    r = Rep(
        name="Test Rep", email="rep@pragmattie-sync.example", region="EMEA", quarterly_quota=100_000
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture
def account(client, rep):
    body = {
        "name": "Northbeam Logistics",
        "industry": "Transportation",
        "employee_count": 150,
        "annual_revenue": "25000000",
        "region": "EMEA",
        "owner_id": rep.id,
    }
    return client.post("/api/v1/accounts", json=body).json()
