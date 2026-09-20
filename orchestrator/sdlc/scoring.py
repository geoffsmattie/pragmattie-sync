"""Stage one of the PR risk score: a transparent weighted rubric, computed in plain Python.

Ten signals add up to at most 110 points, capped at 100. Every signal keeps the points it
contributed, so the score can always be explained. History-based signals are point-in-time: they
only use what was known before the PR was opened (an incident counts only once it had opened),
so scoring old PRs to calibrate the rubric can't peek at the answer.

Try it with `python -m sdlc.risk explain <pr>` and grade it with `python -m sdlc.risk calibrate`.
Stage two (a bounded Claude adjustment) and the agent that uses this come later in Phase 4.
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from sdlc.tables import CIRun, Incident, PullRequest

MAX_POINTS = {
    "change_size": 20,
    "blast_radius": 10,
    "module_risk": 20,
    "schema_migration": 15,
    "author_record": 10,
    "tests_with_change": 10,
    "ci_signal": 10,
    "review_depth": 5,
    "timing": 5,
    "rework_churn": 5,
}
SHRINKAGE = 10  # a module's rate is pulled toward the team rate as if it had this many more PRs
MIN_AUTHOR_PRS = 5  # below this, the author's record is treated as average


@dataclass(frozen=True)
class Features:
    """Everything the rubric reads about one PR, gathered once."""

    lines: int
    files_changed: int
    modules_touched: int
    touches_migration: bool
    docs_only: bool
    test_files_changed: int
    review_count: int
    rework_commits: int
    real_ci_failures: int
    at: datetime  # when the change would land
    module_rate: float  # incident rate of this PR's module before it was opened
    max_module_rate: float  # highest such rate across modules
    author_ratio: float | None  # author's recent incident rate over the team's; None = unknown


@dataclass(frozen=True)
class Score:
    signals: dict[str, int]
    total: int  # capped at 100


# --- the ten signals: each takes what it needs and returns points up to its maximum -------------


def change_size(lines: int) -> int:
    for limit, points in ((50, 0), (150, 5), (400, 10), (800, 15)):
        if lines < limit:
            return points
    return 20


def blast_radius(files: int, modules: int) -> int:
    base = 0 if files < 3 else 2 if files < 6 else 4 if files < 11 else 6 if files < 21 else 7
    return min(10, base + (3 if modules > 2 else 0))


def module_risk(rate: float, highest: float) -> int:
    return round(20 * rate / highest) if highest > 0 else 0


def schema_migration(touches_migration: bool) -> int:
    return 15 if touches_migration else 0


def author_record(ratio: float | None) -> int:
    return 5 if ratio is None else min(10, round(5 * ratio))


def tests_with_change(lines: int, docs_only: bool, test_files: int) -> int:
    return 10 if not docs_only and lines >= 50 and test_files == 0 else 0


def ci_signal(real_failures: int) -> int:
    return {0: 0, 1: 4, 2: 7}.get(real_failures, 10)


def review_depth(reviews: int, lines: int) -> int:
    return 5 if reviews == 0 or (reviews == 1 and lines >= 400) else 0


def timing(at: datetime) -> int:
    return 5 if at.weekday() >= 4 or not 8 <= at.hour < 18 else 0  # Friday, weekend, off-hours


def rework_churn(commits_after_review: int) -> int:
    return {0: 0, 1: 2, 2: 3}.get(commits_after_review, 5)


def score_features(f: Features) -> Score:
    signals = {
        "change_size": change_size(f.lines),
        "blast_radius": blast_radius(f.files_changed, f.modules_touched),
        "module_risk": module_risk(f.module_rate, f.max_module_rate),
        "schema_migration": schema_migration(f.touches_migration),
        "author_record": author_record(f.author_ratio),
        "tests_with_change": tests_with_change(f.lines, f.docs_only, f.test_files_changed),
        "ci_signal": ci_signal(f.real_ci_failures),
        "review_depth": review_depth(f.review_count, f.lines),
        "timing": timing(f.at),
        "rework_churn": rework_churn(f.rework_commits),
    }
    return Score(signals=signals, total=min(100, sum(signals.values())))


# --- gathering features from the database (point-in-time) ---------------------------------------


def _incident_prs_before(reference: datetime):
    return select(Incident.caused_by_pr_id).where(
        Incident.caused_by_pr_id.is_not(None), Incident.opened_at < reference
    )


def module_rates(db: Session, reference: datetime) -> tuple[dict[str, float], float]:
    """Incident rate per module (smoothed toward the team rate) and the team rate."""
    known = _incident_prs_before(reference)
    rows = db.execute(
        select(
            PullRequest.module,
            func.count(),
            func.sum(case((PullRequest.id.in_(known), 1), else_=0)),
        )
        .where(PullRequest.state == "merged", PullRequest.merged_at < reference)
        .group_by(PullRequest.module)
    ).all()
    total = sum(n for _, n, _ in rows)
    team = sum(hits or 0 for _, _, hits in rows) / total if total else 0.0
    smoothed = {
        module: ((hits or 0) + team * SHRINKAGE) / (n + SHRINKAGE) for module, n, hits in rows
    }
    return smoothed, team


def author_ratio(db: Session, pr: PullRequest, reference: datetime, team: float) -> float | None:
    if pr.author_id is None or team <= 0:
        return None
    recent = list(
        db.scalars(
            select(PullRequest.id)
            .where(
                PullRequest.author_id == pr.author_id,
                PullRequest.state == "merged",
                PullRequest.merged_at < reference,
            )
            .order_by(PullRequest.merged_at.desc())
            .limit(20)
        )
    )
    if len(recent) < MIN_AUTHOR_PRS:
        return None
    hits = db.scalar(
        select(func.count()).where(
            PullRequest.id.in_(recent), PullRequest.id.in_(_incident_prs_before(reference))
        )
    )
    return (hits / len(recent)) / team


def compute_features(db: Session, pr: PullRequest, now: datetime | None = None) -> Features:
    reference = pr.created_at  # what was known when the PR was opened
    rates, team = module_rates(db, reference)
    failures = db.scalar(
        select(func.count()).where(
            CIRun.pull_request_id == pr.id, CIRun.conclusion == "failure", CIRun.flaky.is_(False)
        )
    )
    return Features(
        lines=pr.additions + pr.deletions,
        files_changed=pr.files_changed,
        modules_touched=pr.modules_touched,
        touches_migration=pr.touches_migration,
        docs_only=pr.docs_only,
        test_files_changed=pr.test_files_changed,
        review_count=pr.review_count,
        rework_commits=pr.rework_commits,
        real_ci_failures=failures or 0,
        at=pr.merged_at or now or pr.created_at,
        module_rate=rates.get(pr.module, team),
        max_module_rate=max(rates.values(), default=0.0),
        author_ratio=author_ratio(db, pr, reference, team),
    )


def score_pull_request(db: Session, pr: PullRequest, now: datetime | None = None) -> Score:
    return score_features(compute_features(db, pr, now))


def features_digest(features: Features) -> dict:
    data = asdict(features)
    data["at"] = features.at.isoformat()
    return data
