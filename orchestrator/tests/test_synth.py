from sqlalchemy import func, select

from sdlc.metrics import ci_health, quality_by_module, sprint_velocity
from sdlc.synth import build, has_synthetic, reset
from sdlc.tables import Incident, PullRequest, Sprint
from tests.conftest import NOW


def test_volumes_look_like_six_months_of_work(history):
    assert history["sprints"] == 13
    assert history["issues"] > 250
    assert history["pull_requests"] > 400
    assert history["ci_runs"] > 2500
    assert history["deployments"] > 50
    assert 8 <= history["incidents"] <= 25


def test_nothing_is_dated_in_the_future(db, history):
    assert db.scalar(select(func.max(PullRequest.created_at))) <= NOW
    assert db.scalar(select(func.max(Incident.opened_at))) <= NOW
    last = db.scalar(select(Sprint).order_by(Sprint.start_date.desc()))
    assert last.start_date <= NOW.date() <= last.end_date  # current sprint in progress


def test_built_in_patterns_are_present(db, history):
    modules = {m["module"]: m for m in quality_by_module(db)}
    # Billing & Auth changes cause incidents far more often than average.
    others = [m["incident_rate"] for k, m in modules.items() if k != "billing_auth"]
    assert modules["billing_auth"]["incident_rate"] > 2 * (sum(others) / len(others))
    # Forecasting and integrations work overruns its estimates.
    assert modules["forecasting"]["days_per_point"] > 1.3 * modules["leads"]["days_per_point"]
    assert modules["integrations"]["days_per_point"] > 1.3 * modules["pipeline"]["days_per_point"]
    # The integrations suite is the flaky one.
    suites = {s["suite"]: s for s in ci_health(db, 52, NOW)["by_suite"]}
    assert suites["integrations-e2e"]["flaky_rate"] > 3 * suites["api"]["flaky_rate"]


def test_large_prs_are_riskier(db, history):
    def rate(where):
        rows = db.execute(
            select(func.count(), func.sum(PullRequest.caused_incident)).where(
                PullRequest.state == "merged", where
            )
        ).one()
        return (rows[1] or 0) / rows[0]

    assert rate(PullRequest.additions > 500) > 2 * rate(PullRequest.additions <= 250)


def test_velocity_dips_in_holiday_sprints(db, history):
    sprints = sprint_velocity(db, NOW.date())
    by_name = {s["sprint"]: s for s in sprints}
    # Sprint 5 contains Memorial Day and follows the first release.
    typical = sorted(s["committed"] for s in sprints)[len(sprints) // 2]
    assert by_name["Sprint 5"]["committed"] < typical


def test_repeatable_and_resettable(db, history):
    assert has_synthetic(db)
    reset(db)
    assert not has_synthetic(db)
    assert build(db, now=NOW) == history
