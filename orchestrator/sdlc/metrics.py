"""Delivery metrics computed from the signal tables.

Kept free of web concerns so the same functions feed the dashboard, the agents and tests.
Calculations run in Python over modest row counts, so they behave the same on MySQL,
Postgres or SQLite.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from sdlc.tables import CIRun, Deployment, Incident, Issue, PullRequest, Sprint


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _week(moment: datetime | date) -> date:
    day = moment.date() if isinstance(moment, datetime) else moment
    return day - timedelta(days=day.weekday())


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def dora_summary(db: Session, now: datetime, days: int = 30) -> dict:
    """The four DORA-style delivery measures for the last `days`, with the prior period."""

    def window(start: datetime, end: datetime) -> dict:
        deploys = list(
            db.scalars(
                select(Deployment).where(
                    Deployment.deployed_at >= start, Deployment.deployed_at < end
                )
            )
        )
        prs = list(
            db.scalars(
                select(PullRequest).where(
                    PullRequest.merged_at >= start, PullRequest.merged_at < end
                )
            )
        )
        incidents = list(
            db.scalars(
                select(Incident).where(Incident.opened_at >= start, Incident.opened_at < end)
            )
        )
        failed_deploys = {i.deployment_id for i in incidents if i.deployment_id} | {
            d.id for d in deploys if d.status == "rolled_back"
        }
        restore = [_hours(i.opened_at, i.resolved_at) for i in incidents if i.resolved_at]
        lead = [_hours(p.created_at, p.merged_at) for p in prs]
        return {
            "deploys_per_week": _round(len(deploys) / (days / 7)),
            "lead_time_hours": _round(median(lead)) if lead else None,
            "change_failure_rate": _round(
                len(failed_deploys & {d.id for d in deploys}) / len(deploys) * 100
            )
            if deploys
            else None,
            "time_to_restore_hours": _round(median(restore)) if restore else None,
            "deployments": len(deploys),
            "incidents": len(incidents),
        }

    current_start = now - timedelta(days=days)
    return {
        "days": days,
        "current": window(current_start, now),
        "previous": window(current_start - timedelta(days=days), current_start),
    }


def sprint_velocity(db: Session, today: date) -> list[dict]:
    """Committed vs completed story points per sprint (completed = closed by sprint end)."""
    sprints = list(db.scalars(select(Sprint).order_by(Sprint.start_date)))
    issues = list(db.scalars(select(Issue).where(Issue.sprint_id.is_not(None))))
    by_sprint = defaultdict(list)
    for issue in issues:
        by_sprint[issue.sprint_id].append(issue)
    out = []
    for s in sprints:
        items = by_sprint.get(s.id, [])
        cutoff = datetime.combine(s.end_date + timedelta(days=1), datetime.min.time())
        out.append(
            {
                "sprint": s.name,
                "start": s.start_date,
                "end": s.end_date,
                "in_progress": s.start_date <= today <= s.end_date,
                "committed": sum(i.estimate_points or 0 for i in items),
                "completed": sum(
                    i.estimate_points or 0 for i in items if i.closed_at and i.closed_at < cutoff
                ),
                "goal": s.goal,
            }
        )
    return out


def pr_cycle_time(db: Session, weeks: int, now: datetime) -> list[dict]:
    """Median and 85th-percentile hours from PR opened to merged, per week merged."""
    since = now - timedelta(weeks=weeks)
    prs = db.scalars(
        select(PullRequest).where(
            PullRequest.merged_at.is_not(None), PullRequest.merged_at >= since
        )
    )
    by_week = defaultdict(list)
    for p in prs:
        by_week[_week(p.merged_at)].append(_hours(p.created_at, p.merged_at))
    return [
        {
            "week": week,
            "median_hours": _round(median(v)),
            "p85_hours": _round(_percentile(v, 0.85)),
            "merged": len(v),
        }
        for week, v in sorted(by_week.items())
    ]


def pr_cycle_time_by_sprint(db: Session, now: datetime) -> list[dict]:
    """Median and 85th-percentile PR cycle time for PRs merged during each sprint."""
    sprints = list(db.scalars(select(Sprint).order_by(Sprint.start_date)))
    if not sprints:
        return []
    first = datetime.combine(sprints[0].start_date, datetime.min.time())
    prs = list(
        db.scalars(
            select(PullRequest).where(
                PullRequest.merged_at.is_not(None), PullRequest.merged_at >= first
            )
        )
    )
    out = []
    for s in sprints:
        start = datetime.combine(s.start_date, datetime.min.time())
        end = datetime.combine(s.end_date + timedelta(days=1), datetime.min.time())
        hours = [_hours(p.created_at, p.merged_at) for p in prs if start <= p.merged_at < end]
        out.append(
            {
                "sprint": s.name,
                "start": s.start_date,
                "in_progress": s.start_date <= now.date() <= s.end_date,
                "median_hours": _round(median(hours)) if hours else None,
                "p85_hours": _round(_percentile(hours, 0.85)),
                "merged": len(hours),
            }
        )
    return out


def ci_health(db: Session, weeks: int, now: datetime) -> dict:
    """Pass rate and flaky-failure rate per test suite, overall and per week."""
    since = now - timedelta(weeks=weeks)
    runs = list(db.scalars(select(CIRun).where(CIRun.started_at >= since)))
    suites = defaultdict(lambda: {"runs": 0, "passed": 0, "flaky": 0})
    weekly = defaultdict(lambda: {"runs": 0, "passed": 0})
    for r in runs:
        s = suites[r.suite]
        s["runs"] += 1
        s["passed"] += r.conclusion == "success"
        s["flaky"] += r.flaky
        w = weekly[_week(r.started_at)]
        w["runs"] += 1
        w["passed"] += r.conclusion == "success"
    return {
        "by_suite": [
            {
                "suite": name,
                "runs": s["runs"],
                "pass_rate": _round(s["passed"] / s["runs"] * 100),
                "flaky_rate": _round(s["flaky"] / s["runs"] * 100),
            }
            for name, s in sorted(suites.items())
        ],
        "by_week": [
            {"week": week, "runs": w["runs"], "pass_rate": _round(w["passed"] / w["runs"] * 100)}
            for week, w in sorted(weekly.items())
        ],
    }


def quality_by_module(db: Session) -> list[dict]:
    """Per module: PRs, incidents, incident rate and estimate accuracy (days per point)."""
    prs = db.execute(
        select(
            PullRequest.module,
            func.count(),
            # Cast: summing a Boolean column would otherwise come back as a bool.
            func.sum(cast(PullRequest.caused_incident, Integer)),
        )
        .where(PullRequest.state == "merged")
        .group_by(PullRequest.module)
    ).all()
    incidents = dict(
        db.execute(select(Incident.module, func.count()).group_by(Incident.module)).all()
    )
    by_module = defaultdict(lambda: [0.0, 0])
    for module, points, days in db.execute(
        select(Issue.module, Issue.estimate_points, Issue.actual_days).where(
            Issue.actual_days.is_not(None), Issue.estimate_points > 0
        )
    ):
        by_module[module][0] += days
        by_module[module][1] += points
    out = []
    for module, merged, caused in prs:
        if module is None:
            continue
        days, points = by_module.get(module, (0.0, 0))
        out.append(
            {
                "module": module,
                "merged_prs": merged,
                "incidents": incidents.get(module, 0),
                "incident_rate": _round(float(caused or 0) / merged * 100) if merged else 0.0,
                "days_per_point": _round(days / points, 2) if points else None,
            }
        )
    return sorted(out, key=lambda m: m["incident_rate"], reverse=True)


def sources(db: Session) -> dict:
    """How many rows came from synthetic history vs the real GitHub repository."""
    out = {}
    for name, model in (
        ("issues", Issue),
        ("pull_requests", PullRequest),
        ("ci_runs", CIRun),
        ("deployments", Deployment),
        ("incidents", Incident),
    ):
        out[name] = dict(
            db.execute(select(model.source, func.count()).group_by(model.source)).all()
        )
    return out
