import os

# Tests use a throwaway SQLite file, so they need no MySQL server or GitHub token.
os.environ["DATABASE_URL"] = "sqlite:///./test_orch.db"
os.environ["GITHUB_TOKEN"] = ""
os.environ["GITHUB_REPO"] = ""

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from sdlc.db import Base, SessionLocal, engine  # noqa: E402
from sdlc.synth import build  # noqa: E402

NOW = datetime(2026, 9, 18, 12, 0)


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
def history(db):
    return build(db, now=NOW)
