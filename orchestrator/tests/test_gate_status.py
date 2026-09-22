from datetime import datetime

from sqlalchemy import select

from sdlc import gate_status
from sdlc.agents.gate import Gate
from sdlc.tables import GateStatus, PullRequest

NOW = datetime(2026, 9, 23, 10, 0)


def make_pr(db, number=7):
    pr = PullRequest(
        source="github", external_id=f"pr-{number}", number=number, title="x", created_at=NOW
    )
    db.add(pr)
    db.flush()
    return pr


def test_upsert_creates_one_row_per_pr(db):
    pr = make_pr(db)
    gate = Gate("pending", "pending", ("human sign-off",), "T1: waiting for human sign-off")
    row = gate_status.upsert(db, pr, gate, tier="T1", mode="enforce", now=NOW)

    assert row.pull_request_id == pr.id
    assert (row.tier, row.state, row.would_be) == ("T1", "pending", "pending")
    assert row.missing == ["human sign-off"]
    assert row.description == "T1: waiting for human sign-off"
    assert row.mode == "enforce" and row.updated_at == NOW
    assert db.scalar(select(GateStatus).where(GateStatus.pull_request_id == pr.id)) is row


def test_a_second_upsert_replaces_the_row_in_place_not_appends(db):
    pr = make_pr(db)
    first = Gate("pending", "pending", ("human sign-off",), "waiting")
    gate_status.upsert(db, pr, first, tier="T1", mode="enforce", now=NOW)

    later = NOW.replace(minute=30)
    second = Gate("success", "success", (), "requirements met")
    row = gate_status.upsert(db, pr, second, tier="T1", mode="enforce", now=later)

    assert db.scalar(select(GateStatus).where(GateStatus.pull_request_id == pr.id)) is row
    all_rows = list(db.scalars(select(GateStatus)))
    assert len(all_rows) == 1  # replaced, not a second row
    assert (row.state, row.missing, row.updated_at) == ("success", [], later)


def test_missing_is_stored_as_a_plain_list_not_a_tuple(db):
    pr = make_pr(db)
    gate = Gate("failure", "failure", ("a successful risk assessment",), "fallback")
    row = gate_status.upsert(db, pr, gate, tier="T2", mode="shadow", now=NOW)
    assert row.missing == ["a successful risk assessment"]
    assert isinstance(row.missing, list)
