from datetime import datetime, timedelta

from sqlalchemy import select

from sdlc.forecaster import ForecastRunner, moved
from sdlc.synth import reset
from sdlc.tables import AgentDecision, Forecast, Issue
from tests.conftest import NOW

EPICS = 4


def forecasts(db):
    return list(db.scalars(select(Forecast).order_by(Forecast.id)))


def audit(db):
    return list(
        db.scalars(
            select(AgentDecision)
            .where(AgentDecision.agent == "forecaster")
            .order_by(AgentDecision.id)
        )
    )


def runner():
    return ForecastRunner("shadow", runs=500)


def test_mode_off_does_nothing_at_all(db, history):
    assert ForecastRunner("off").poll_once(NOW) == {"mode": "off"}
    assert forecasts(db) == [] and audit(db) == []


def test_first_poll_forecasts_the_sprint_and_every_epic_with_an_audit_row_each(db, history):
    summary = runner().poll_once(NOW)
    assert summary["assessed"] == 1 + EPICS

    rows = forecasts(db)
    assert [r.kind for r in rows].count("sprint") == 1 and len(rows) == 1 + EPICS
    assert {r.trigger for r in rows} == {"schedule"}
    sprint = next(r for r in rows if r.kind == "sprint")
    assert sprint.subject == "Sprint 13" and sprint.source == "synthetic"
    assert sprint.end_date and sprint.on_time_probability is not None
    assert sprint.p50 <= sprint.p85

    decisions = audit(db)
    assert [d.subject_id for d in decisions] == [r.id for r in rows]  # one per forecast
    d = decisions[0]
    assert (d.subject_type, d.status, d.trigger) == ("sprint", "ok", "schedule")
    assert d.output["subject"] == "Sprint 13" and "P50" in d.output["rationale"]
    assert d.output["confidence"] == sprint.on_time_probability
    assert d.model_id is None and d.input_tokens is None  # no Claude call: it costs nothing


def test_nothing_changed_means_nothing_new(db, history):
    agent = runner()
    agent.poll_once(NOW)
    summary = agent.poll_once(NOW + timedelta(seconds=30))
    assert (summary["assessed"], summary["unchanged"]) == (0, 1 + EPICS)
    assert len(forecasts(db)) == 1 + EPICS


def test_a_story_opened_under_an_epic_reforecasts_only_that_epic_and_the_date_moves(db, history):
    agent = runner()
    agent.poll_once(NOW)
    for n in range(3):
        db.add(
            Issue(
                source="github",
                external_id=f"issue-{900 + n}",
                number=900 + n,
                title="A story opened live",
                module="leads",
                estimate_points=3,
                state="open",
                created_at=NOW,
                epic="AI lead scoring",
            )
        )
    db.commit()

    summary = agent.poll_once(NOW + timedelta(minutes=1))
    assert (summary["assessed"], summary["unchanged"]) == (1, EPICS)
    newest = forecasts(db)[-1]
    assert (newest.kind, newest.subject, newest.trigger) == ("epic", "AI lead scoring", "change")
    assert newest.source == "mixed" and newest.remaining_real >= 3

    shift = moved(db, "epic", "AI lead scoring")
    assert shift["latest"].id == newest.id and shift["previous"] is not None
    assert shift["p50_days"] > 0 and shift["p85_days"] > 0  # the date moved out


def test_a_new_day_reforecasts_everything_on_schedule(db, history):
    agent = runner()
    agent.poll_once(NOW)
    summary = agent.poll_once(NOW + timedelta(days=1))
    assert summary["assessed"] == 1 + EPICS
    assert {r.trigger for r in forecasts(db)[-(1 + EPICS) :]} == {"schedule"}


def test_a_forced_run_is_recorded_as_manual(db, history):
    agent = runner()
    agent.poll_once(NOW)
    agent.poll_once(NOW, force=True)
    assert {r.trigger for r in forecasts(db)[-(1 + EPICS) :]} == {"manual"}


def test_regenerating_the_history_forgets_saved_forecasts(db, history):
    runner().poll_once(NOW)
    reset(db)
    assert forecasts(db) == [] and audit(db) == []


def test_moved_is_none_before_any_forecast(db):
    assert moved(db, "epic", "Nothing yet") is None


def test_same_inputs_same_day_give_the_same_forecast(db, history):
    runner().poll_once(NOW)
    runner().poll_once(NOW, force=True)
    first, again = forecasts(db)[0], forecasts(db)[1 + EPICS]
    assert (first.subject, first.p50, first.p85, first.seed) == (
        again.subject,
        again.p50,
        again.p85,
        again.seed,
    )
    assert first.created_at == datetime(2026, 9, 18, 12, 0)
