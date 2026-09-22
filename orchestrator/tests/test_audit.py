from datetime import datetime, timedelta

from sdlc.audit import count_decisions, list_decisions, record_decision, serialize_decision

NOW = datetime(2026, 9, 23, 12, 0)


def make_decision(db, *, agent="pr_risk", subject_id, status="ok", tier="T1", when=None, **kw):
    return record_decision(
        db,
        agent=agent,
        agent_version="v1",
        subject_type=kw.pop("subject_type", "pr"),
        subject_source=kw.pop("subject_source", "github"),
        subject_id=subject_id,
        trigger="poll",
        now=when or NOW,
        head_sha=f"sha-{subject_id}",
        tier=tier,
        status=status,
        **kw,
    )


def test_list_decisions_orders_newest_first(db):
    make_decision(db, subject_id=1, when=NOW - timedelta(hours=2))
    make_decision(db, subject_id=2, when=NOW - timedelta(hours=1))
    make_decision(db, subject_id=3, when=NOW)

    rows = list_decisions(db)

    assert [r.subject_id for r in rows] == [3, 2, 1]


def test_list_decisions_filters_by_agent_status_and_tier(db):
    make_decision(
        db, agent="pr_risk", subject_id=1, status="ok", tier="T0", when=NOW - timedelta(minutes=2)
    )
    make_decision(
        db,
        agent="pr_risk",
        subject_id=2,
        status="error",
        tier="T2",
        when=NOW - timedelta(minutes=1),
    )
    make_decision(
        db, agent="triage", subject_id=3, status="ok", tier="T0", subject_type="issue", when=NOW
    )

    assert [r.subject_id for r in list_decisions(db, agent="triage")] == [3]
    assert [r.subject_id for r in list_decisions(db, status="error")] == [2]
    assert [r.subject_id for r in list_decisions(db, tier="T0")] == [3, 1]


def test_list_decisions_paginates(db):
    for i in range(5):
        make_decision(db, subject_id=i, when=NOW - timedelta(minutes=i))

    page = list_decisions(db, limit=2, offset=1)

    assert [r.subject_id for r in page] == [1, 2]


def test_count_decisions_matches_the_same_filters_as_list(db):
    make_decision(db, agent="pr_risk", subject_id=1, status="ok")
    make_decision(db, agent="pr_risk", subject_id=2, status="error")
    make_decision(db, agent="triage", subject_id=3, status="ok", subject_type="issue")

    assert count_decisions(db) == 3
    assert count_decisions(db, agent="pr_risk") == 2
    assert count_decisions(db, status="error") == 1


def test_serialize_decision_is_json_safe(db):
    row = make_decision(
        db, subject_id=7, signals={"timing": 5}, human_override={"before": "T1", "after": "T2"}
    )

    out = serialize_decision(row)

    assert out["subject_id"] == 7
    assert out["signals"] == {"timing": 5}
    assert out["human_override"] == {"before": "T1", "after": "T2"}
    assert isinstance(out["created_at"], str)
