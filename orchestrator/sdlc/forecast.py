"""Delivery forecast: when will a sprint's open work be done, and which items are slipping?

A Monte Carlo simulation over past throughput, the blueprint's first delivery-forecast model.
It needs no estimates to be right: it resamples how many issues the team actually closed on
each working day of the last six sprints, and plays the remaining work forward 10,000 times.
The spread of finish dates gives P50 (a coin flip) and P85 (the date to promise), and the share
of runs that finish by the sprint's last day is the on-time probability.

Deterministic on purpose: each forecast is seeded from the sprint and the day, so re-running it
(or re-running a demo) the same day gives the same numbers, and they change only when the work
or the day does.

Items at risk are explained, not predicted by the simulation: an open item's expected effort is
its points times its module's historical days-per-point (Forecasting and Integrations run well
over estimate), and it is flagged when that effort no longer fits in the working days left.

Epics are forecast the same way, from the epic's own pace (how many of its stories closed on
each working day) and its open stories, simulated and real alike. An epic has no deadline, so
it gets P50/P85 dates but no on-time probability; a real story opened under it live pushes
those dates out, which is the demo's "the forecast moves" moment.

Usage:
    python -m sdlc.forecast             # the current sprint (synthetic history) and every epic
    python -m sdlc.forecast --runs 2000
"""

import argparse
import math
import random
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.tables import Issue, PullRequest, Sprint

HISTORY_DAYS = 84  # six two-week sprints of throughput to resample
RUNS = 10_000
HORIZON = 260  # working days (about a year); a run still unfinished by then never finishes
# An item counts as running over only when it's well past its expected effort, not just past it:
# half again as long, and at least two working days more (small items are noisy).
OVERRUN_FACTOR, OVERRUN_SLACK_DAYS = 1.5, 2


@dataclass(frozen=True)
class ItemRisk:
    number: int | None
    title: str
    module: str | None
    points: int
    expected_days: float  # working days of effort the module's history implies
    remaining_days: float  # of that, what's still to do
    started: date | None  # first PR opened, if any
    reason: str


@dataclass(frozen=True)
class SprintForecast:
    sprint: str
    source: str
    start_date: date
    end_date: date
    as_of: date
    remaining_items: int
    remaining_points: int
    working_days_left: int  # today through the sprint's last day
    p50: date | None  # None: not finished within the horizon in half the runs
    p85: date | None
    on_time_probability: float  # share of runs done by end_date, 0-1
    throughput_mean: float  # issues closed per working day over the history window
    history_days: int
    runs: int
    seed: int
    at_risk: tuple[ItemRisk, ...]


@dataclass(frozen=True)
class EpicForecast:
    epic: str
    as_of: date
    remaining_items: int
    remaining_real: int  # of remaining_items, how many are real GitHub issues
    remaining_points: int
    closed_items: int
    p50: date | None
    p85: date | None
    throughput_mean: float  # this epic's stories closed per working day
    history_days: int
    runs: int
    seed: int


# --- dates -------------------------------------------------------------------------------------


def is_workday(day: date) -> bool:
    return day.weekday() < 5


def working_days(start: date, end: date) -> list[date]:
    """Every weekday from start to end, both included."""
    days, day = [], start
    while day <= end:
        if is_workday(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def next_workday(day: date) -> date:
    day += timedelta(days=1)
    while not is_workday(day):
        day += timedelta(days=1)
    return day


def _first_workday(day: date) -> date:
    return day if is_workday(day) else next_workday(day)


# --- the simulation ----------------------------------------------------------------------------


def daily_throughput(
    db: Session,
    *,
    today: date,
    source: str | None = None,
    epic: str | None = None,
    days: int = HISTORY_DAYS,
) -> list[int]:
    """Issues closed on each working day of the `days` before today (today is unfinished),
    optionally only one source's or one epic's."""
    window = working_days(today - timedelta(days=days), today - timedelta(days=1))
    if not window:
        return []
    query = select(Issue.closed_at).where(
        Issue.closed_at >= datetime.combine(window[0], datetime.min.time()),
        Issue.closed_at < datetime.combine(today, datetime.min.time()),
    )
    if source:
        query = query.where(Issue.source == source)
    if epic:
        query = query.where(Issue.epic == epic)
    closed = db.scalars(query)
    per_day = Counter(moment.date() for moment in closed)
    return [per_day.get(day, 0) for day in window]


def simulate(
    remaining: int, samples: list[int], *, start: date, runs: int, seed: int
) -> list[date | None]:
    """One finish date per run: draw a past day's throughput for each working day from `start`
    until the remaining items are done. None means not done within HORIZON working days."""
    first = _first_workday(start)
    if remaining <= 0:
        return [first] * runs
    if not samples or not any(samples):
        return [None] * runs
    rng = random.Random(seed)
    results: list[date | None] = []
    for _ in range(runs):
        done, day = 0, first
        for _step in range(HORIZON):
            done += rng.choice(samples)
            if done >= remaining:
                results.append(day)
                break
            day = next_workday(day)
        else:
            results.append(None)
    return results


def percentile_date(results: list[date | None], pct: float) -> date | None:
    """The date by which `pct` of runs finished (runs that never finish sort last)."""
    if not results:
        return None
    ordered = sorted(results, key=lambda d: (d is None, d or date.min))
    return ordered[max(0, math.ceil(pct * len(ordered)) - 1)]


def seed_for(sprint: Sprint, today: date) -> int:
    return zlib.crc32(f"{sprint.source}:{sprint.id}:{today.isoformat()}".encode())


def epic_seed(epic: str, today: date) -> int:
    return zlib.crc32(f"epic:{epic}:{today.isoformat()}".encode())


# --- items at risk -----------------------------------------------------------------------------


def days_per_point(db: Session, source: str) -> dict[str | None, float]:
    """Historical effort per estimated point, per module, from closed work. Key None: overall."""
    totals: dict[str | None, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for module, points, days in db.execute(
        select(Issue.module, Issue.estimate_points, Issue.actual_days).where(
            Issue.source == source, Issue.actual_days.is_not(None), Issue.estimate_points > 0
        )
    ):
        for key in (module, None):
            totals[key][0] += days
            totals[key][1] += points
    return {key: days / points for key, (days, points) in totals.items() if points}


def _item_risks(
    db: Session, items: list[Issue], today: date, end: date, days_left: int, source: str
) -> list[ItemRisk]:
    rates = days_per_point(db, source)
    overall = rates.get(None, 1.0)
    first_pr: dict[int, datetime] = {}
    for issue_id, opened in db.execute(
        select(PullRequest.issue_id, PullRequest.created_at).where(
            PullRequest.issue_id.in_([i.id for i in items])
        )
    ):
        if issue_id not in first_pr or opened < first_pr[issue_id]:
            first_pr[issue_id] = opened

    risks = []
    for item in items:
        points = item.estimate_points or 0
        rate = rates.get(item.module, overall)
        expected = points * rate
        started = first_pr[item.id].date() if item.id in first_pr else None
        elapsed = len(working_days(started, today - timedelta(days=1))) if started else 0
        remaining = max(0.0, expected - elapsed)
        overrun = started is not None and elapsed >= max(
            expected * OVERRUN_FACTOR, expected + OVERRUN_SLACK_DAYS
        )
        if remaining <= days_left and not overrun:
            continue
        module = item.module or "unassigned"
        history = f"{module} work has taken {rate:.1f} working days per point"
        if overrun:
            reason = (
                f"In progress {elapsed} working days against about {expected:.1f} expected "
                f"({points} pt; {history}): well over, still open."
            )
        else:
            where = f"started {started:%b %d}, " if started else "not started, "
            reason = (
                f"{points} pt, {where}about {remaining:.1f} working days of work left but "
                f"{days_left} left in the sprint ({history})."
            )
        risks.append(
            ItemRisk(
                number=item.number,
                title=item.title,
                module=item.module,
                points=points,
                expected_days=round(expected, 1),
                remaining_days=round(remaining, 1),
                started=started,
                reason=reason,
            )
        )
    # Worst shortfall first: the items a planner would look at first.
    return sorted(risks, key=lambda r: r.remaining_days - days_left, reverse=True)


# --- the forecast ------------------------------------------------------------------------------


def current_sprint(db: Session, today: date, source: str) -> Sprint | None:
    return db.scalar(
        select(Sprint)
        .where(Sprint.source == source, Sprint.start_date <= today, Sprint.end_date >= today)
        .limit(1)
    )


def sprint_forecast(
    db: Session,
    today: date,
    *,
    sprint: Sprint | None = None,
    source: str = "synthetic",
    runs: int = RUNS,
) -> SprintForecast | None:
    """Forecast one sprint (default: the one in progress). None when there's no such sprint."""
    sprint = sprint or current_sprint(db, today, source)
    if sprint is None:
        return None
    open_items = list(
        db.scalars(select(Issue).where(Issue.sprint_id == sprint.id, Issue.state == "open"))
    )
    samples = daily_throughput(db, today=today, source=source)
    seed = seed_for(sprint, today)
    results = simulate(len(open_items), samples, start=today, runs=runs, seed=seed)
    on_time = sum(1 for d in results if d is not None and d <= sprint.end_date)
    days_left = len(working_days(today, sprint.end_date))
    return SprintForecast(
        sprint=sprint.name,
        source=source,
        start_date=sprint.start_date,
        end_date=sprint.end_date,
        as_of=today,
        remaining_items=len(open_items),
        remaining_points=sum(i.estimate_points or 0 for i in open_items),
        working_days_left=days_left,
        p50=percentile_date(results, 0.50),
        p85=percentile_date(results, 0.85),
        on_time_probability=on_time / runs if runs else 0.0,
        throughput_mean=round(sum(samples) / len(samples), 2) if samples else 0.0,
        history_days=len(samples),
        runs=runs,
        seed=seed,
        at_risk=tuple(_item_risks(db, open_items, today, sprint.end_date, days_left, source)),
    )


def epic_names(db: Session) -> list[str]:
    return sorted(db.scalars(select(Issue.epic).where(Issue.epic.is_not(None)).distinct()))


def epic_forecast(db: Session, today: date, epic: str, *, runs: int = RUNS) -> EpicForecast:
    """When will this epic's open stories, simulated and real, be done at its recent pace?"""
    stories = list(db.scalars(select(Issue).where(Issue.epic == epic)))
    open_items = [i for i in stories if i.state == "open"]
    samples = daily_throughput(db, today=today, epic=epic)
    seed = epic_seed(epic, today)
    results = simulate(len(open_items), samples, start=today, runs=runs, seed=seed)
    return EpicForecast(
        epic=epic,
        as_of=today,
        remaining_items=len(open_items),
        remaining_real=sum(1 for i in open_items if i.source == "github"),
        remaining_points=sum(i.estimate_points or 0 for i in open_items),
        closed_items=len(stories) - len(open_items),
        p50=percentile_date(results, 0.50),
        p85=percentile_date(results, 0.85),
        throughput_mean=round(sum(samples) / len(samples), 2) if samples else 0.0,
        history_days=len(samples),
        runs=runs,
        seed=seed,
    )


def _when(d: date | None) -> str:
    return f"{d:%a %b %d}" if d else "not in sight"


def describe_epic(f: EpicForecast) -> str:
    real = f" ({f.remaining_real} real)" if f.remaining_real else ""
    weekly = f.throughput_mean * 5
    return (
        f"{f.epic}: {f.remaining_items} stories open{real}, {f.remaining_points} points; "
        f"closing about {weekly:.1f} a week. P50 {_when(f.p50)} · P85 {_when(f.p85)}."
    )


def describe(f: SprintForecast) -> str:
    lines = [
        f"{f.sprint} [{f.source}] ends {f.end_date:%a %b %d}; as of {f.as_of:%a %b %d}, "
        f"{f.working_days_left} working days left.",
        f"Open: {f.remaining_items} issues ({f.remaining_points} points).",
        f"Throughput: {f.throughput_mean} issues per working day over the last "
        f"{f.history_days} working days.",
        f"P50 {_when(f.p50)} · P85 {_when(f.p85)} · "
        f"{f.on_time_probability:.0%} chance of finishing by the sprint's end "
        f"({f.runs:,} runs, seed {f.seed}).",
    ]
    if f.at_risk:
        lines += ["", f"At risk ({len(f.at_risk)}):"]
        lines += [f"  #{r.number} {r.title[:60]}: {r.reason}" for r in f.at_risk]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Forecast the current sprint and the epics.")
    parser.add_argument("--runs", type=int, default=RUNS)
    parser.add_argument("--source", default="synthetic", choices=["synthetic", "github"])
    args = parser.parse_args(argv)

    from sdlc.db import SessionLocal

    today = date.today()
    with SessionLocal() as db:
        forecast = sprint_forecast(db, today, source=args.source, runs=args.runs)
        epics = [epic_forecast(db, today, name, runs=args.runs) for name in epic_names(db)]
    print(describe(forecast) if forecast else f"No {args.source} sprint is in progress today.")
    if epics:
        print("\nEpics:")
        print("\n".join("  " + describe_epic(e) for e in epics))


if __name__ == "__main__":
    main()
