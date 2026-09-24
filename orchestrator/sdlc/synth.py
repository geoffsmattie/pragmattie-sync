"""Synthetic engineering history for PragMattie Sync.

About six months of believable delivery data (sprints, issues, pull requests, CI runs,
deployments and incidents) so the prediction models have something to learn from before
the real repository has much history. Every row is stored with source="synthetic" and the
dashboard labels it as simulated.

Patterns deliberately built in (the models in Phase 4-5 should rediscover them):
  * Forecasting and Integrations work runs 1.5-2x over estimate.
  * Large PRs touching Billing & Auth, or schema migrations, cause most incidents.
  * The integrations test suite fails intermittently (~8% flaky).
  * Changes merged on Fridays are more likely to cause incidents.
  * Velocity dips in holiday sprints and in the sprint after a big release.
  * Engineer profiles: Marcus ships big PRs with few defects; Dana ships small, steady
    PRs; Tomas (newer) has slower reviews and more rework.
  * Four epics (the same names as the real backlog's) run through the last four sprints,
    each with unscheduled stories still to do, so epics have a pace and a finish to forecast.

Usage:
    python -m sdlc.synth              # add history (refuses if synthetic data exists)
    python -m sdlc.synth --if-empty   # add only when there is no synthetic data yet
    python -m sdlc.synth --reset      # replace existing synthetic data
"""

import argparse
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from sdlc.db import SessionLocal
from sdlc.tables import (
    AgentDecision,
    Approval,
    CIRun,
    Deployment,
    Engineer,
    Forecast,
    Incident,
    Issue,
    PullRequest,
    Sprint,
)

SEED = 7
SOURCE = "synthetic"
SPRINT_DAYS = 14
SPRINT_COUNT = 13  # ~6 months, the last one in progress


@dataclass(frozen=True)
class Persona:
    login: str
    name: str
    role: str
    share: float  # share of engineering work
    pr_size: int  # typical lines added per PR
    speed: float  # >1 = takes longer than estimate
    defect: float  # multiplier on incident risk
    rework: float  # typical rework commits after review
    review_hours: float  # how long others wait for this person's reviews


PERSONAS = [
    Persona("priya-n", "Priya N.", "Engineering manager", 0.08, 60, 1.0, 1.0, 0.5, 6),
    Persona("marcus-l", "Marcus L.", "Senior backend engineer", 0.30, 420, 0.85, 0.5, 0.6, 5),
    Persona("dana-k", "Dana K.", "Frontend engineer (Vue)", 0.27, 90, 1.0, 0.8, 0.8, 6),
    Persona("tomas-r", "Tomas R.", "Backend engineer", 0.22, 200, 1.3, 1.6, 2.5, 20),
    Persona("aisha-b", "Aisha B.", "QA / SDET", 0.13, 150, 1.0, 0.6, 0.7, 8),
]
NON_CODERS = [Persona("leo-m", "Leo M.", "Product manager", 0, 0, 1, 1, 0, 0)]

# module: (share of work, estimate overrun range, incident risk multiplier, migration rate)
MODULES = {
    "leads": (0.16, (0.8, 1.2), 0.8, 0.10),
    "accounts": (0.12, (0.8, 1.2), 1.0, 0.15),
    "pipeline": (0.16, (0.9, 1.3), 1.2, 0.12),
    "forecasting": (0.16, (1.5, 2.0), 1.5, 0.08),
    "integrations": (0.14, (1.5, 2.0), 1.4, 0.05),
    "billing_auth": (0.10, (0.9, 1.4), 4.0, 0.30),
    "platform": (0.16, (0.8, 1.2), 1.0, 0.05),
}
WORK = {
    "leads": ["lead scoring", "lead import", "duplicate detection", "lead assignment rules"],
    "accounts": ["account hierarchy", "contact roles", "account merge", "account timeline"],
    "pipeline": ["stage history", "deal board filters", "bulk stage update", "close-date alerts"],
    "forecasting": ["weighted forecast", "forecast snapshots", "quota tracking", "rollup math"],
    "integrations": ["email sync", "calendar sync", "webhook retries", "CSV export"],
    "billing_auth": ["SSO login", "seat billing", "plan upgrades", "role permissions"],
    "platform": ["API pagination", "audit logging", "search indexing", "job queue"],
}
VERBS = {"feature": ["Add", "Build", "Support"], "bug": ["Fix", "Resolve"], "chore": ["Refactor"]}
# epic: (its module, work still in its backlog). Names match orchestrator/backlog/backlog.yaml.
EPICS = {
    "AI lead scoring": (
        "leads",
        ["score explanations", "scoring model retraining", "score history", "score thresholds"],
    ),
    "Multi-currency forecasting": (
        "forecasting",
        ["currency conversion rates", "per-currency quota", "FX rollup math", "FX snapshots"],
    ),
    "Salesforce import": (
        "integrations",
        ["Salesforce field mapping", "Salesforce OAuth", "import dry run", "import conflicts"],
    ),
    "SOC 2 audit logging": (
        "platform",
        ["audit event schema", "audit log retention", "audit log export", "admin access logs"],
    ),
}
EPIC_SPRINTS = 6  # epics started this many sprints ago (the forecast's whole history window)
SUITES = ["api", "web", "migrations", "integrations-e2e"]
# The real CI's orchestrator job, added in Phase 6 so the simulated suites match the real ones
# (plus integrations-e2e, which is simulated only). Drawn from its own stream: see _make_ci_runs.
LATE_SUITES = ["orchestrator"]
SUITE_SECONDS = {
    "api": 150,
    "web": 110,
    "migrations": 90,
    "integrations-e2e": 540,
    "orchestrator": 240,
}
MODULE_LABELS = {
    "leads": "Leads",
    "accounts": "Accounts",
    "pipeline": "Pipeline",
    "forecasting": "Forecasting",
    "integrations": "Integrations",
    "billing_auth": "Billing & Auth",
    "platform": "Platform",
}
HOLIDAYS = [(1, 1), (5, 25), (7, 4), (9, 7), (11, 26), (12, 25)]  # rough US holiday dates


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _has_holiday(start: date, end: date) -> bool:
    return any(
        start <= date(start.year, m, d) <= end or start <= date(end.year, m, d) <= end
        for m, d in HOLIDAYS
    )


def _at(day: date, hour: float) -> datetime:
    return datetime.combine(day, time()) + timedelta(hours=hour)


def _workday_after(moment: datetime, hours: float) -> datetime:
    """Add elapsed hours, pushing anything that lands on a weekend to Monday morning."""
    result = moment + timedelta(hours=hours)
    while result.weekday() >= 5:
        result = _at(result.date() + timedelta(days=1), 9.5)
    return result


def build(db: Session, now: datetime | None = None, seed: int = SEED) -> dict[str, int]:
    """Generate the history. Another `seed` gives different random draws (and incidents), which
    is how the risk rubric is calibrated across many histories instead of one lucky draw."""
    rng = random.Random(seed)
    now = now or datetime.now().replace(microsecond=0)
    today = now.date()

    engineers = {
        p.login: Engineer(login=p.login, name=p.name, role=p.role, source=SOURCE)
        for p in PERSONAS + NON_CODERS
    }
    db.add_all(engineers.values())
    db.flush()
    personas = {p.login: p for p in PERSONAS}

    # Sprints start on even ISO weeks, so in an odd week the current one began last Monday.
    current_start = _monday(today) - timedelta(days=7 if _monday(today).isocalendar()[1] % 2 else 0)
    first_start = current_start - timedelta(days=SPRINT_DAYS * (SPRINT_COUNT - 1))
    release_sprints = {3, 7, 11}  # sprints ending in a big release

    counts = dict.fromkeys(
        ["sprints", "issues", "pull_requests", "ci_runs", "deployments", "incidents"], 0
    )
    merged_prs: list[PullRequest] = []
    risks: list[float] = []
    issue_number = 0
    pr_number = 0

    for i in range(SPRINT_COUNT):
        start = first_start + timedelta(days=SPRINT_DAYS * i)
        end = start + timedelta(days=SPRINT_DAYS - 1)
        sprint = Sprint(
            name=f"Sprint {i + 1}",
            start_date=start,
            end_date=end,
            goal=("Release " + f"2026.{i // 4 + 1}") if i in release_sprints else None,
            source=SOURCE,
        )
        db.add(sprint)
        db.flush()
        counts["sprints"] += 1

        capacity = 75.0  # team story points per sprint
        if _has_holiday(start, end):
            capacity *= 0.7
        if i - 1 in release_sprints:
            capacity *= 0.8
        committed_target = capacity * rng.uniform(1.05, 1.3)  # teams tend to over-commit

        committed = 0
        while committed < committed_target:
            module = rng.choices(list(MODULES), [m[0] for m in MODULES.values()])[0]
            kind = rng.choices(["feature", "bug", "chore"], [60, 28, 12])[0]
            points = rng.choice([1, 2, 3, 5, 8] if kind == "feature" else [1, 2, 3])
            author = rng.choices(PERSONAS, [p.share for p in PERSONAS])[0]
            overrun = rng.uniform(*MODULES[module][1])
            actual_days = round(points * 0.7 * overrun * author.speed * rng.uniform(0.8, 1.2), 1)
            begin = start + timedelta(days=rng.randint(0, 6))
            created = _at(begin - timedelta(days=rng.randint(1, 20)), rng.uniform(9, 17))
            closed = _workday_after(_at(begin, rng.uniform(9, 12)), actual_days * 24 * 1.4)
            is_closed = closed <= now
            issue_number += 1
            issue = Issue(
                source=SOURCE,
                external_id=f"syn-issue-{issue_number}",
                number=issue_number,
                title=f"{rng.choice(VERBS[kind])} {rng.choice(WORK[module])}",
                module=module,
                type=kind,
                priority=rng.choices(["p1", "p2", "p3"], [15, 55, 30])[0],
                estimate_points=points,
                actual_days=actual_days if is_closed else None,
                state="closed" if is_closed else "open",
                created_at=created,
                closed_at=closed if is_closed else None,
                sprint_id=sprint.id,
                assignee_id=engineers[author.login].id,
            )
            db.add(issue)
            db.flush()
            committed += points
            counts["issues"] += 1

            # Each issue ships as one or two pull requests.
            pr_total = 1 if points <= 1 else rng.choice([1, 2] if points <= 3 else [2, 3])
            for n in range(pr_total):
                opened = _at(begin, rng.uniform(10, 17)) + timedelta(
                    days=actual_days * (n + 0.5) / pr_total
                )
                if opened > now:
                    continue
                pr_number += 1
                pr, risk = _make_pr(
                    rng,
                    pr_number,
                    n,
                    pr_total,
                    issue,
                    author,
                    personas,
                    engineers,
                    opened,
                    now,
                    seed,
                )
                db.add(pr)
                db.flush()
                counts["pull_requests"] += 1
                counts["ci_runs"] += _make_ci_runs(db, rng, pr, seed)
                if pr.state == "merged":
                    merged_prs.append(pr)
                    risks.append(risk)

    counts["epic_backlog"] = _add_epics(db, seed, now, current_start, issue_number)
    _assign_incidents(rng, merged_prs, risks)
    counts["deployments"], counts["incidents"] = _deploy(db, rng, merged_prs, now)
    db.commit()
    return counts


def _add_epics(db: Session, seed: int, now: datetime, current_start: date, last_number: int) -> int:
    """Tag recent feature work with its epic and add each epic's unscheduled backlog.

    Uses its own random stream, so the rest of the history (and the risk calibration that is
    locked against it) comes out exactly as it did before epics existed."""
    rng = random.Random(f"{seed}:epics")
    since = datetime.combine(
        current_start - timedelta(days=SPRINT_DAYS * (EPIC_SPRINTS - 1)), time()
    )
    by_module = {module: name for name, (module, _) in EPICS.items()}
    recent = db.scalars(
        select(Issue)
        .where(Issue.source == SOURCE, Issue.type == "feature", Issue.created_at >= since)
        .order_by(Issue.id)
    )
    for issue in recent:
        if issue.module in by_module and rng.random() < 0.8:
            issue.epic = by_module[issue.module]

    added = 0
    for name, (module, work) in EPICS.items():
        for _ in range(rng.randint(4, 8)):
            last_number += 1
            added += 1
            db.add(
                Issue(
                    source=SOURCE,
                    external_id=f"syn-issue-{last_number}",
                    number=last_number,
                    title=f"{rng.choice(VERBS['feature'])} {rng.choice(work)}",
                    module=module,
                    type="feature",
                    priority=rng.choices(["p1", "p2", "p3"], [20, 60, 20])[0],
                    estimate_points=rng.choice([2, 3, 3, 5, 5, 8]),
                    state="open",
                    created_at=_at(now.date() - timedelta(days=rng.randint(3, 40)), 10),
                    epic=name,
                )
            )
    db.flush()
    return added


def _make_pr(rng, number, part, parts, issue, author, personas, engineers, opened, now, seed):
    module = issue.module
    size = max(5, int(rng.lognormvariate(math.log(author.pr_size), 0.7)))
    if issue.type == "bug":
        size = max(5, size // 3)
    migration = issue.type != "chore" and rng.random() < MODULES[module][3]
    reviewer = rng.choice([p for p in personas.values() if p.login != author.login])
    first_review = max(0.5, rng.gauss(reviewer.review_hours, reviewer.review_hours / 3))
    rework = max(0, int(rng.gauss(author.rework, 1)))
    cycle_hours = first_review + rework * rng.uniform(2, 8) + rng.uniform(1, 6)
    merged = _workday_after(opened, cycle_hours)
    state = "merged"
    if rng.random() < 0.05:
        state = "closed"  # abandoned
    if merged > now:
        state = "open"

    # Incident risk: the pattern the PR risk model should learn.
    risk = 0.01 * MODULES[module][2] * author.defect
    if size > 500:
        risk *= 4
    elif size > 250:
        risk *= 2
    if migration:
        risk *= 3
    if merged.weekday() == 4:  # Friday
        risk *= 2

    # Draw order matters: these two draws stay where the constructor used to make them.
    files_changed = max(1, size // rng.randint(25, 60))
    deletions = int(size * rng.uniform(0.1, 0.6))

    # File facts come from their own stream, so adding them never shifts the draws above.
    frng = random.Random(f"{seed}:files:{number}")
    docs_only = issue.type == "chore" and frng.random() < 0.6
    test_files = 0
    modules_touched = 1
    if not docs_only:
        if frng.random() < (0.85 if issue.type == "bug" else 0.7):
            test_files = min(files_changed, max(1, round(files_changed * frng.uniform(0.2, 0.5))))
        if files_changed >= 4 and frng.random() < 0.2:
            modules_touched += frng.randint(1, 2)
    # Docs and config changes don't cause incidents, so the calibration has something to hold.
    pr_risk = risk if state == "merged" and not docs_only else 0.0

    return PullRequest(
        source=SOURCE,
        external_id=f"syn-pr-{number}",
        number=number,
        title=issue.title if parts == 1 else f"{issue.title} (part {part + 1} of {parts})",
        author_id=engineers[author.login].id,
        issue_id=issue.id,
        module=module,
        files_changed=files_changed,
        additions=size,
        deletions=deletions,
        touches_migration=migration,
        test_files_changed=test_files,
        docs_only=docs_only,
        modules_touched=modules_touched,
        review_count=1 + rework // 2 + (1 if size > 400 else 0),
        first_review_hours=round(first_review, 1),
        rework_commits=rework,
        state=state,
        created_at=opened,
        merged_at=merged if state == "merged" else None,
        closed_at=merged if state in ("merged", "closed") else None,
    ), pr_risk


def _assign_incidents(rng: random.Random, prs: list[PullRequest], risks: list[float]) -> None:
    """Pick which merged PRs caused incidents: about 3% of them, weighted steeply by risk,
    so the patterns are clear enough to learn from even with a few hundred PRs."""
    target = max(1, round(len(prs) * 0.03))
    pool = list(zip(prs, risks, strict=True))
    for _ in range(min(target, len(pool))):
        weights = [r**2 for _, r in pool]
        pr, _ = pool.pop(rng.choices(range(len(pool)), weights)[0])
        pr.caused_incident = True
        pr.reverted = rng.random() < 0.5


def _make_ci_runs(db: Session, rng: random.Random, pr: PullRequest, seed: int) -> int:
    """Every suite on every push. The original four draw from `rng` in their original order;
    later suites draw from a per-PR stream, so adding them never shifts the rest of the history."""
    late = random.Random(f"{seed}:ci:{pr.number}")
    pushes = 1 + pr.rework_commits
    runs = 0
    for push in range(pushes):
        started = pr.created_at + timedelta(hours=push * rng.uniform(1, 6))
        for suite in SUITES + LATE_SUITES:
            r = late if suite in LATE_SUITES else rng
            real_fail = r.random() < (0.12 if push == 0 else 0.04) * (
                1.5 if pr.additions > 400 else 1
            )
            flaky = not real_fail and r.random() < (0.08 if suite == "integrations-e2e" else 0.01)
            db.add(
                CIRun(
                    source=SOURCE,
                    external_id=f"syn-ci-{pr.number}-{push}-{suite}",
                    pull_request_id=pr.id,
                    suite=suite,
                    conclusion="failure" if (real_fail or flaky) else "success",
                    flaky=flaky,
                    started_at=started,
                    duration_seconds=int(SUITE_SECONDS[suite] * r.uniform(0.8, 1.3)),
                )
            )
            runs += 1
            if flaky:  # a re-run passes
                db.add(
                    CIRun(
                        source=SOURCE,
                        external_id=f"syn-ci-{pr.number}-{push}-{suite}-rerun",
                        pull_request_id=pr.id,
                        suite=suite,
                        conclusion="success",
                        flaky=False,
                        started_at=started + timedelta(minutes=12),
                        duration_seconds=540,
                    )
                )
                runs += 1
    return runs


def _deploy(db: Session, rng: random.Random, merged: list[PullRequest], now: datetime):
    """Ship merged PRs in weekday afternoon deploys; raise incidents for risky ones."""
    merged.sort(key=lambda p: p.merged_at)
    deployments = incidents = 0
    if not merged:
        return 0, 0
    day = merged[0].merged_at.date()
    pending: list[PullRequest] = []
    index = 0
    while day <= now.date():
        while index < len(merged) and merged[index].merged_at.date() <= day:
            pending.append(merged[index])
            index += 1
        deploy_at = _at(day, 15 + rng.random())
        if pending and day.weekday() < 5 and rng.random() < 0.75 and deploy_at <= now:
            bad = [p for p in pending if p.caused_incident]
            deployments += 1
            deployment = Deployment(
                source=SOURCE,
                version=f"2026.{day.timetuple().tm_yday:03d}.{deployments}",
                deployed_at=deploy_at,
                pr_count=len(pending),
                status="rolled_back" if any(p.reverted for p in bad) else "success",
            )
            db.add(deployment)
            db.flush()
            for pr in bad:
                sev = (
                    "sev1" if pr.module == "billing_auth" else rng.choice(["sev2", "sev3", "sev3"])
                )
                opened = deploy_at + timedelta(hours=rng.uniform(0.5, 20))
                restore = rng.uniform(0.5, 3) if pr.reverted else rng.uniform(2, 14)
                db.add(
                    Incident(
                        source=SOURCE,
                        title=f"{MODULE_LABELS[pr.module]} degraded after {deployment.version}",
                        severity=sev,
                        module=pr.module,
                        opened_at=opened,
                        resolved_at=opened + timedelta(hours=restore)
                        if opened + timedelta(hours=restore) <= now
                        else None,
                        caused_by_pr_id=pr.id,
                        deployment_id=deployment.id,
                    )
                )
                incidents += 1
            pending = []
        day += timedelta(days=1)
    return deployments, incidents


def reset(db: Session) -> None:
    # Approvals point at pull requests; MySQL won't delete a PR that still has one.
    synthetic_prs = select(PullRequest.id).where(PullRequest.source == SOURCE)
    db.execute(delete(Approval).where(Approval.pull_request_id.in_(synthetic_prs)))
    # Audit rows name PRs by number, and the reset regenerates those numbers. A correction row
    # points at an earlier one, so unlink them first: MySQL checks that row by row.
    synthetic_rows = AgentDecision.subject_source == SOURCE
    db.execute(update(AgentDecision).where(synthetic_rows).values(supersedes_id=None))
    db.execute(delete(AgentDecision).where(synthetic_rows))
    # Saved forecasts describe the history being replaced (and epics mix in real stories, so
    # their rows aren't all "synthetic"): forget them all, with the audit rows of the agents
    # whose subjects they are (the forecaster's, and the planner's proposals about them).
    db.execute(delete(AgentDecision).where(AgentDecision.agent.in_(["forecaster", "planner"])))
    db.execute(delete(Forecast))
    db.execute(update(Issue).where(Issue.source == SOURCE).values(sprint_id=None))
    for model in (Incident, CIRun, Deployment, PullRequest, Issue, Sprint, Engineer):
        db.execute(delete(model).where(model.source == SOURCE))
    db.commit()


def has_synthetic(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Sprint).where(Sprint.source == SOURCE)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic engineering history.")
    parser.add_argument("--if-empty", action="store_true", help="skip if history already exists")
    parser.add_argument("--reset", action="store_true", help="replace existing synthetic history")
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.reset:
            reset(db)
        elif has_synthetic(db):
            if args.if_empty:
                print("Synthetic history already present; skipping.")
                return
            raise SystemExit("Synthetic history already exists. Use --reset to replace it.")
        counts = build(db)
        print("Generated synthetic history: " + ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
