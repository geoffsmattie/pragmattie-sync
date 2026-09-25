from datetime import date, datetime

from sdlc.accuracy import (
    MIN_POINTS,
    backtest_sprint,
    forecast_accuracy,
    report,
    risk_accuracy,
    selector_accuracy,
    triage_accuracy,
)
from sdlc.audit import record_decision
from sdlc.tables import Issue, Sprint
from sdlc.tiers import load_policy
from tests.conftest import NOW

RUNS = 500  # enough to test the wiring; the real report uses the forecaster's 10,000


def test_the_forecast_backtest_uses_only_what_was_known_then(db, history):
    rows = forecast_accuracy(db, NOW.date(), runs=RUNS)
    assert rows["simulated"] and rows["graded"] >= 8
    assert rows["targets"] == {"p50_hit_rate": 0.5, "p85_hit_rate": 0.85}
    for r in rows["sprints"]:
        assert r["as_of"] < r["end_date"] and r["p50"] <= r["p85"]
        assert r["p85_met"] or not r["p50_met"]  # meeting P50 means meeting P85 too
    last = rows["sprints"][-1]
    assert last["p85_hit_rate_so_far"] == rows["p85_hit_rate"]

    # Closing a sprint's items later can't change what it was forecast on its third day.
    sprint = db.query(Sprint).filter_by(name=rows["sprints"][-2]["sprint"]).one()
    before = backtest_sprint(db, sprint, runs=RUNS)
    for issue in db.query(Issue).filter_by(sprint_id=sprint.id):
        if issue.closed_at is None:
            issue.closed_at, issue.state = datetime(2026, 9, 17, 12), "closed"
    db.flush()
    after = backtest_sprint(db, sprint, runs=RUNS)
    assert (before["p50"], before["p85"]) == (after["p50"], after["p85"])


def test_the_risk_trend_counts_incident_prs_the_score_flagged(db, history):
    r = risk_accuracy(db, load_policy())
    assert r["simulated"] and r["incident_prs"] == sum(s["incident_prs"] for s in r["sprints"])
    assert 0 < r["caught"] <= r["incident_prs"]
    assert r["recall"] == round(r["caught"] / r["incident_prs"], 3)
    assert r["sprints"][-1]["recall_so_far"] == r["recall"]
    assert r["real"] == {"merged_prs": 0, "incident_prs": 0}


def _issue(db, number, **labels):
    db.add(
        Issue(
            source="github",
            external_id=f"issue-{number}",
            number=number,
            title=f"Issue {number}",
            state="open",
            created_at=datetime(2026, 9, 21, 9),
            **labels,
        )
    )


def _triaged(db, number, when, **output):
    record_decision(
        db,
        agent="triage",
        agent_version="v1",
        subject_type="issue",
        subject_source="github",
        subject_id=number,
        trigger="poll",
        now=when,
        head_sha=f"v{number}",
        status="ok",
        output={"module": "leads", "type": "bug", "priority": "p2", "estimate_points": 3, **output},
    )


def test_triage_counts_the_labels_people_changed_afterwards(db):
    _issue(db, 6, module="leads", type="bug", priority="p2", estimate_points=3)
    _issue(db, 7, module="pipeline", type="bug", priority="p2", estimate_points=5)  # corrected
    _triaged(db, 6, datetime(2026, 9, 21, 10))
    _triaged(db, 7, datetime(2026, 9, 29, 10))
    record_decision(  # a manual trial never counts
        db,
        agent="triage",
        agent_version="v1",
        subject_type="issue",
        subject_source="github",
        subject_id=6,
        trigger="trial",
        status="ok",
        output={"module": "billing_auth"},
    )
    db.commit()
    r = triage_accuracy(db)
    assert (r["total"], r["corrected"], r["kept_rate"], r["enough"]) == (2, 1, 0.5, 2 >= MIN_POINTS)
    assert [w["week"] for w in r["weeks"]] == ["2026-09-21", "2026-09-28"]
    assert r["weeks"][1]["module_changed"] == 1 and r["weeks"][1]["points_changed"] == 1


def test_the_test_selector_trend_counts_misses_per_week(db):
    for n, status in ((1, "ok"), (2, "missed"), (3, "ok")):
        record_decision(
            db,
            agent="test_selector",
            agent_version="v1",
            subject_type="pr",
            subject_source="github",
            subject_id=n,
            trigger="ci_result",
            status=status,
            now=datetime(2026, 9, 22, 9),
            head_sha=f"s{n}",
        )
    db.commit()
    r = selector_accuracy(db)
    assert (r["total"], r["missed"], r["miss_rate"], r["enough"]) == (3, 1, 0.333, False)


def test_the_report_has_all_four_and_marks_what_is_simulated(db, history):
    r = report(db, today=date(2026, 9, 18))
    assert r["forecast"]["simulated"] and r["risk"]["simulated"]
    assert not r["triage"]["simulated"] and not r["test_selector"]["simulated"]
    assert report(db, today=date(2026, 9, 18))["forecast"] is r["forecast"]  # cached
