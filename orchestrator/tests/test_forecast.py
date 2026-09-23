from datetime import date, datetime, timedelta

from sdlc.forecast import (
    daily_throughput,
    epic_forecast,
    epic_names,
    percentile_date,
    simulate,
    sprint_forecast,
    working_days,
)
from sdlc.tables import Issue, PullRequest, Sprint

FRI = date(2026, 9, 18)
MON = date(2026, 9, 21)


def test_working_days_skip_weekends():
    assert working_days(FRI, MON) == [FRI, MON]
    assert working_days(MON, FRI) == []


def test_steady_throughput_finishes_on_a_predictable_workday():
    # Two a day, five to go: Fri (2), Mon (4), Tue (6) -> done Tuesday, in every run.
    results = simulate(5, [2], start=FRI, runs=50, seed=1)
    assert set(results) == {date(2026, 9, 22)}


def test_same_seed_same_answer_and_a_new_seed_can_differ():
    samples = [0, 1, 1, 2, 3, 5]
    a = simulate(20, samples, start=MON, runs=500, seed=7)
    assert a == simulate(20, samples, start=MON, runs=500, seed=7)
    assert a != simulate(20, samples, start=MON, runs=500, seed=8)


def test_nothing_left_is_done_today_and_no_throughput_is_never_done():
    assert set(simulate(0, [1], start=MON, runs=3, seed=1)) == {MON}
    never = simulate(4, [0, 0, 0], start=MON, runs=3, seed=1)
    assert never == [None, None, None] and percentile_date(never, 0.5) is None


def test_percentiles_put_runs_that_never_finish_last():
    results = [MON, None, FRI, date(2026, 9, 22)]
    assert percentile_date(results, 0.5) == MON
    assert percentile_date(results, 0.75) == date(2026, 9, 22)
    assert percentile_date(results, 1.0) is None


def _issue(
    db, n, *, sprint=None, closed=None, points=3, module="leads", actual=None, source="s", epic=None
):
    issue = Issue(
        source=source,
        external_id=f"i{n}",
        number=n,
        title=f"Issue {n}",
        module=module,
        estimate_points=points,
        actual_days=actual,
        state="closed" if closed else "open",
        created_at=datetime(2026, 8, 1, 9),
        closed_at=closed,
        sprint_id=sprint.id if sprint else None,
        epic=epic,
    )
    db.add(issue)
    db.flush()
    return issue


def test_throughput_counts_closures_per_workday_before_today_for_one_source(db):
    at = lambda d: datetime.combine(d, datetime.min.time()) + timedelta(hours=11)  # noqa: E731
    _issue(db, 1, closed=at(FRI))
    _issue(db, 2, closed=at(FRI))
    _issue(db, 3, closed=at(date(2026, 9, 17)))
    _issue(db, 4, closed=at(MON))  # today: unfinished, not history
    _issue(db, 5, closed=at(FRI), source="other")
    samples = daily_throughput(db, today=MON, source="s", days=5)
    assert samples == [0, 1, 2]  # Wed 16, Thu 17, Fri 18 (the weekend isn't a working day)


def _sprint(db, start, end, source="s"):
    sprint = Sprint(name="Sprint X", start_date=start, end_date=end, source=source)
    db.add(sprint)
    db.flush()
    return sprint


def test_items_that_no_longer_fit_are_flagged_with_a_reason(db):
    today = date(2026, 9, 23)  # Wednesday; the sprint ends Friday: 3 working days left
    sprint = _sprint(db, date(2026, 9, 14), date(2026, 9, 25))
    # History: integrations work takes 2 working days per point, leads work 0.5.
    _issue(db, 1, closed=datetime(2026, 9, 1, 12), points=2, module="integrations", actual=4.0)
    _issue(db, 2, closed=datetime(2026, 9, 2, 12), points=2, module="leads", actual=1.0)
    big = _issue(db, 10, sprint=sprint, points=3, module="integrations")  # 6 days, not started
    small = _issue(db, 11, sprint=sprint, points=2, module="leads")  # 1 day: fits
    stuck = _issue(db, 12, sprint=sprint, points=1, module="leads")  # 0.5 expected
    db.add(
        PullRequest(
            source="s", title="wip", issue_id=stuck.id, created_at=datetime(2026, 9, 14, 10)
        )
    )
    db.flush()

    f = sprint_forecast(db, today, sprint=sprint, source="s", runs=200)
    flagged = {r.number: r for r in f.at_risk}
    assert set(flagged) == {big.number, stuck.number} and small.number not in flagged
    assert f.at_risk[0].number == big.number  # worst shortfall first
    assert "not started" in flagged[big.number].reason
    assert "2.0 working days per point" in flagged[big.number].reason
    assert "well over" in flagged[stuck.number].reason
    assert (f.remaining_items, f.remaining_points, f.working_days_left) == (3, 6, 3)


def test_forecast_of_the_current_synthetic_sprint_is_repeatable(db, history):
    first = sprint_forecast(db, FRI, runs=2000)
    again = sprint_forecast(db, FRI, runs=2000)
    assert first == again
    assert first.sprint == "Sprint 13" and first.remaining_items > 0
    assert first.p50 <= first.p85
    assert 0.0 <= first.on_time_probability <= 1.0
    assert first.history_days == len(working_days(FRI - timedelta(days=84), FRI - timedelta(1)))


def test_more_open_work_pushes_the_date_out(db, history):
    before = sprint_forecast(db, FRI, runs=2000)
    sprint = db.query(Sprint).filter_by(name="Sprint 13").one()
    for n in range(20):
        _issue(db, 10_000 + n, sprint=sprint, source="synthetic")
    after = sprint_forecast(db, FRI, runs=2000)
    assert after.remaining_items == before.remaining_items + 20
    assert after.p85 > before.p85
    assert after.on_time_probability <= before.on_time_probability


def test_no_sprint_in_progress_means_no_forecast(db):
    assert sprint_forecast(db, FRI, source="s") is None


def test_an_epic_counts_real_and_simulated_stories_at_its_own_pace(db):
    today = date(2026, 9, 23)
    for n, day in enumerate([14, 15, 16, 17, 18, 21, 22]):  # one story closed most workdays
        _issue(
            db, n, closed=datetime(2026, 9, day, 12), epic="Salesforce import", source="synthetic"
        )
    _issue(db, 50, closed=datetime(2026, 9, 22, 12), epic=None)  # other work: not its pace
    for n in range(100, 104):
        _issue(db, n, epic="Salesforce import", source="synthetic", points=3)
    _issue(db, 200, epic="Salesforce import", source="github", points=5)

    f = epic_forecast(db, today, "Salesforce import", runs=500)
    assert (f.remaining_items, f.remaining_real, f.remaining_points) == (5, 1, 17)
    assert f.closed_items == 7
    assert f.p50 is not None and f.p50 <= f.p85
    assert epic_names(db) == ["Salesforce import"]


def test_a_story_opened_under_an_epic_pushes_its_date_out(db, history):
    today = date(2026, 9, 18)
    before = epic_forecast(db, today, "AI lead scoring", runs=2000)
    for n in range(3):
        _issue(db, 20_000 + n, epic="AI lead scoring", source="github")
    after = epic_forecast(db, today, "AI lead scoring", runs=2000)
    assert after.remaining_real == before.remaining_real + 3
    assert after.p50 > before.p50 and after.p85 > before.p85


def test_an_epic_with_no_recent_pace_is_not_in_sight(db):
    _issue(db, 1, epic="New idea")
    f = epic_forecast(db, date(2026, 9, 23), "New idea", runs=50)
    assert f.remaining_items == 1 and f.p50 is None and f.p85 is None
