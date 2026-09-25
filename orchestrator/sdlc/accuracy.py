"""How accurate have the orchestrator's predictions been, and is that changing over time?

Four trends, each graded against what actually happened, each saying whether it is simulated:

  Delivery forecasts   a backtest: every finished simulated sprint is forecast again as of its
                       third working day, by the same seeded engine the forecaster uses, using only
                       what was known that day; then the P50 and P85 dates are checked against the
                       day its last item actually closed. A well-calibrated P85 is met about 85% of
                       the time, a P50 about half the time.
  Risk score           per sprint, the merged simulated PRs scored as they would have been (the
                       rubric, as `sdlc.risk calibrate` does), and how many of the PRs that went on
                       to cause an incident the score had put at T2 or above, plus T0's incidents.
                       Few incidents per sprint, so the cumulative line is the one to read.
  Triage agent         real issues only: per week, how many issues it labelled and how many of
                       those a person has since changed (module, type, priority or points).
  Test selector        real PRs only: per week, commits whose CI finished and how many had a job
                       the selector would have skipped fail (a miss).

The real trends start empty and grow with real work (the demo reset keeps real work; see
sdlc/demo_reset.py). Below MIN_POINTS they report counts, not a trend. Nothing here calls Claude
or GitHub; the two simulated trends are cached per day and history.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdlc import forecast as fc
from sdlc.agents.suite_select import AGENT as SELECTOR_AGENT
from sdlc.agents.triage import AGENT as TRIAGE_AGENT
from sdlc.audit import TRIAL
from sdlc.governance import Facts, assign_tier
from sdlc.scoring import score_pull_request
from sdlc.suite_selector import RESULT
from sdlc.tables import AgentDecision, Issue, PullRequest, Sprint
from sdlc.tiers import TIER_IDS, Policy, load_policy

SIMULATED = "synthetic"
AS_OF_WORKDAY = 2  # forecast each sprint as of its third working day (0-based)
MIN_HISTORY_DAYS = 10  # a sprint forecast needs at least a sprint of throughput behind it
MIN_POINTS = 5  # below this many graded items, a real trend reports counts only
TARGETS = {"p85_hit_rate": 0.85, "p50_hit_rate": 0.5}
DIMENSIONS = ("module", "type", "priority", "points")

_cache: dict[tuple, dict] = {}


# --- delivery forecasts ------------------------------------------------------------------------


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _late_by(forecast: date | None, actual: date | None) -> int | None:
    """Working days the actual finish came after the forecast (negative: before it)."""
    if forecast is None or actual is None:
        return None
    if actual >= forecast:
        return len(fc.working_days(forecast, actual)) - 1
    return -(len(fc.working_days(actual, forecast)) - 1)


def backtest_sprint(db: Session, sprint: Sprint, *, runs: int = fc.RUNS) -> dict | None:
    """One finished sprint forecast as of its third working day, against what happened."""
    days = fc.working_days(sprint.start_date, sprint.end_date)
    if len(days) <= AS_OF_WORKDAY:
        return None
    as_of = days[AS_OF_WORKDAY]
    cutoff = _midnight(as_of)
    items = [
        i
        for i in db.scalars(select(Issue).where(Issue.sprint_id == sprint.id))
        if i.created_at < cutoff and (i.closed_at is None or i.closed_at >= cutoff)
    ]
    samples = fc.daily_throughput(db, today=as_of, source=sprint.source)
    if len(samples) < MIN_HISTORY_DAYS:
        return None  # too early in the history to have forecast it
    results = fc.simulate(
        len(items), samples, start=as_of, runs=runs, seed=fc.seed_for(sprint, as_of)
    )
    p50, p85 = fc.percentile_date(results, 0.5), fc.percentile_date(results, 0.85)
    if items and p85 is None:
        return None  # no throughput to go on, or beyond the horizon: nothing was forecast
    unfinished = any(i.closed_at is None for i in items)
    actual = None if unfinished or not items else max(i.closed_at for i in items).date()
    if not items:
        actual = as_of

    def met(forecast: date | None) -> bool:
        if actual is None:  # still not done today
            return forecast is None
        return forecast is None or actual <= forecast

    return {
        "sprint": sprint.name,
        "as_of": as_of.isoformat(),
        "end_date": sprint.end_date.isoformat(),
        "items": len(items),
        "p50": p50.isoformat() if p50 else None,
        "p85": p85.isoformat() if p85 else None,
        "actual": actual.isoformat() if actual else None,
        "p50_met": met(p50),
        "p85_met": met(p85),
        "p50_error_days": _late_by(p50, actual),
    }


def forecast_accuracy(db: Session, today: date, *, runs: int = fc.RUNS) -> dict:
    sprints = db.scalars(
        select(Sprint)
        .where(Sprint.source == SIMULATED, Sprint.end_date < today)
        .order_by(Sprint.start_date)
    )
    rows = [r for s in sprints if (r := backtest_sprint(db, s, runs=runs))]
    graded = len(rows)
    running, out = {"p50": 0, "p85": 0}, []
    for n, r in enumerate(rows, 1):
        running["p50"] += r["p50_met"]
        running["p85"] += r["p85_met"]
        out.append(
            {
                **r,
                "p50_hit_rate_so_far": round(running["p50"] / n, 3),
                "p85_hit_rate_so_far": round(running["p85"] / n, 3),
            }
        )
    return {
        "simulated": True,
        "sprints": out,
        "graded": graded,
        "p50_hit_rate": round(running["p50"] / graded, 3) if graded else None,
        "p85_hit_rate": round(running["p85"] / graded, 3) if graded else None,
        "targets": {k: TARGETS[k] for k in ("p50_hit_rate", "p85_hit_rate")},
        "as_of_workday": AS_OF_WORKDAY + 1,
    }


# --- risk score --------------------------------------------------------------------------------


def risk_accuracy(db: Session, policy: Policy) -> dict:
    sprints = list(
        db.scalars(select(Sprint).where(Sprint.source == SIMULATED).order_by(Sprint.start_date))
    )
    merged = db.scalars(
        select(PullRequest).where(PullRequest.source == SIMULATED, PullRequest.state == "merged")
    )
    per: dict[str, dict] = {
        s.name: {"sprint": s.name, "prs": 0, "incident_prs": 0, "caught": 0, "t0_incidents": 0}
        for s in sprints
    }
    flagged_from = TIER_IDS.index("T2")
    for pr in merged:
        sprint = next(
            (s for s in sprints if s.start_date <= pr.merged_at.date() <= s.end_date), None
        )
        if sprint is None:
            continue
        facts = Facts(pr.module, pr.touches_migration, pr.docs_only)
        tier = assign_tier(policy, score_pull_request(db, pr).total, facts).tier
        row = per[sprint.name]
        row["prs"] += 1
        if pr.caused_incident:
            row["incident_prs"] += 1
            row["caught"] += TIER_IDS.index(tier) >= flagged_from
            row["t0_incidents"] += tier == "T0"
    rows, incidents, caught = [], 0, 0
    for s in sprints:
        row = per[s.name]
        incidents += row["incident_prs"]
        caught += row["caught"]
        rows.append({**row, "recall_so_far": round(caught / incidents, 3) if incidents else None})
    real = db.scalar(
        select(func.count())
        .select_from(PullRequest)
        .where(PullRequest.source == "github", PullRequest.state == "merged")
    )
    real_incidents = db.scalar(
        select(func.count())
        .select_from(PullRequest)
        .where(PullRequest.source == "github", PullRequest.caused_incident.is_(True))
    )
    return {
        "simulated": True,
        "flagged_from": "T2",
        "sprints": rows,
        "incident_prs": incidents,
        "caught": caught,
        "recall": round(caught / incidents, 3) if incidents else None,
        "t0_incidents": sum(r["t0_incidents"] for r in rows),
        "real": {"merged_prs": real, "incident_prs": real_incidents},
    }


# --- the real ones -----------------------------------------------------------------------------


def _week(moment: datetime) -> str:
    return (moment.date() - timedelta(days=moment.weekday())).isoformat()


def _trend(weeks: dict[str, dict], count_key: str) -> dict:
    rows = [{"week": w, **weeks[w]} for w in sorted(weeks)]
    total = sum(r[count_key] for r in rows)
    return {"simulated": False, "weeks": rows, "total": total, "enough": total >= MIN_POINTS}


def triage_accuracy(db: Session) -> dict:
    """Per week of the agent's latest decision on each real issue: labelled, and since changed."""
    latest: dict[int, AgentDecision] = {}
    for d in db.scalars(
        select(AgentDecision)
        .where(
            AgentDecision.agent == TRIAGE_AGENT,
            AgentDecision.subject_source == "github",
            AgentDecision.status == "ok",
            AgentDecision.trigger != TRIAL,
        )
        .order_by(AgentDecision.created_at, AgentDecision.id)
    ):
        latest[d.subject_id] = d
    issues = {i.number: i for i in db.scalars(select(Issue).where(Issue.source == "github"))}
    weeks: dict[str, dict] = defaultdict(
        lambda: {"labelled": 0, "corrected": 0, **{f"{d}_changed": 0 for d in DIMENSIONS}}
    )
    for number, d in latest.items():
        issue = issues.get(number)
        if issue is None or not d.output:
            continue
        row = weeks[_week(d.created_at)]
        row["labelled"] += 1
        now = {
            "module": issue.module,
            "type": issue.type,
            "priority": issue.priority,
            "points": issue.estimate_points,
        }
        said = {
            "module": d.output.get("module"),
            "type": d.output.get("type"),
            "priority": d.output.get("priority"),
            "points": d.output.get("estimate_points"),
        }
        changed = [dim for dim in DIMENSIONS if now[dim] is not None and now[dim] != said[dim]]
        row["corrected"] += bool(changed)
        for dim in changed:
            row[f"{dim}_changed"] += 1
    out = _trend(weeks, "labelled")
    labelled = out["total"]
    corrected = sum(w["corrected"] for w in out["weeks"])
    return {
        **out,
        "corrected": corrected,
        "kept_rate": round(1 - corrected / labelled, 3) if labelled else None,
    }


def selector_accuracy(db: Session) -> dict:
    """Per week: real commits whose CI finished, and how many the selector would have missed."""
    weeks: dict[str, dict] = defaultdict(lambda: {"settled": 0, "missed": 0})
    for d in db.scalars(
        select(AgentDecision).where(
            AgentDecision.agent == SELECTOR_AGENT,
            AgentDecision.trigger == RESULT,
            AgentDecision.subject_source == "github",
        )
    ):
        row = weeks[_week(d.created_at)]
        row["settled"] += 1
        row["missed"] += d.status == "missed"
    out = _trend(weeks, "settled")
    missed = sum(w["missed"] for w in out["weeks"])
    return {
        **out,
        "missed": missed,
        "miss_rate": round(missed / out["total"], 3) if out["total"] else None,
    }


# --- all of it ---------------------------------------------------------------------------------


def report(db: Session, today: date | None = None, policy: Policy | None = None) -> dict:
    today = today or date.today()
    policy = policy or load_policy()
    key = (
        today,
        db.scalar(select(func.max(PullRequest.id)).where(PullRequest.source == SIMULATED)),
        db.scalar(select(func.max(Issue.id)).where(Issue.source == SIMULATED)),
    )
    if key not in _cache:  # the simulated trends take a few seconds; the history rarely changes
        _cache.clear()
        _cache[key] = {
            "forecast": forecast_accuracy(db, today),
            "risk": risk_accuracy(db, policy),
        }
    return {
        **_cache[key],
        "triage": triage_accuracy(db),
        "test_selector": selector_accuracy(db),
        "min_points": MIN_POINTS,
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
    }


def main() -> None:
    import json

    from sdlc.db import SessionLocal

    with SessionLocal() as db:
        print(json.dumps(report(db), indent=2))


if __name__ == "__main__":
    main()
