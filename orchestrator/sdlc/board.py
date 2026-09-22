"""Derive the delivery board's cards from the signal tables. No stored status field anywhere:
a card's column is always computed fresh from what actually happened, the same philosophy as
the rest of the orchestrator (deterministic in Python, judgment in the model only where needed —
there's no judgment needed here at all, it's plain derivation).

Columns, most-advanced wins, in order:
  Backlog      issue open, not yet triaged
  Triaged      module, type and points set (a successful triage decision exists)
  In progress  an open PR is linked (or, for a synthetic card, additionally in the current sprint)
  In review    the PR has a risk score and the gate isn't blocking it
  Gated        the risk-gate is pending or failing, or a fallback status shows
  Merged       merged, no deployment has picked it up yet
  Production   in a deployment (a rolled-back one keeps the card here, flagged)

A card is keyed by its issue when one exists, otherwise by its PR alone (not every PR traces
back to a tracked issue). If an issue has more than one linked PR, the most advanced one decides
the card's column.

Two data-model facts drive some non-obvious derivations here, both explained where used:
  - Real issues never carry a sprint (nothing assigns one), so "In progress" only requires an
    open PR for real cards; synthetic cards keep the stricter current-sprint rule too.
  - There is no hosted deploy for this project, so a real PR can reach Merged but never
    Production; Production is populated by simulated history only. See CLAUDE.md.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdlc.agents.pr_risk import AGENT as PR_RISK_AGENT
from sdlc.agents.triage import AGENT as TRIAGE_AGENT
from sdlc.tables import (
    AgentDecision,
    Deployment,
    Engineer,
    GateStatus,
    Issue,
    PullRequest,
    Sprint,
)

COLUMNS = (
    "backlog",
    "triaged",
    "in_progress",
    "in_review",
    "gated",
    "merged",
    "production",
)
COLUMN_TITLES = {
    "backlog": "Backlog",
    "triaged": "Triaged",
    "in_progress": "In progress",
    "in_review": "In review",
    "gated": "Gated",
    "merged": "Merged",
    "production": "Production",
}
_RANK = {name: i for i, name in enumerate(COLUMNS)}


@dataclass(frozen=True)
class Decision:
    """The audit row behind a card's tier/score/labels, for the detail drawer."""

    id: int
    agent: str
    created_at: datetime
    tier: str | None
    final_score: int | None
    signals: dict | None
    human_override: dict | None


@dataclass(frozen=True)
class Card:
    key: str  # "issue-<n>" or "pr-<n>", unique within a source
    source: str  # synthetic | github
    issue_number: int | None
    pr_number: int | None
    title: str
    module: str | None
    points: int | None
    owner: str | None
    column: str
    entered_column_at: datetime
    sprint: str | None = None  # None for real cards: nothing assigns them a sprint
    tier: str | None = None
    risk_score: int | None = None
    gate_missing: tuple[str, ...] = ()
    rolled_back: bool = False
    decisions: tuple[Decision, ...] = ()
    transitions: tuple[tuple[str, datetime], ...] = ()  # (column, first known time), for replay


@dataclass(frozen=True)
class Board:
    cards: tuple[Card, ...]
    columns: dict  # column -> {"title", "wip", "median_age_hours"}
    generated_at: datetime


def _decisions_by_subject(db: Session, agent: str) -> dict[tuple[str, int], list[AgentDecision]]:
    out: dict[tuple[str, int], list[AgentDecision]] = defaultdict(list)
    for d in db.scalars(select(AgentDecision).where(AgentDecision.agent == agent)):
        out[(d.subject_source, d.subject_id)].append(d)
    for rows in out.values():
        rows.sort(key=lambda d: d.created_at)
    return out


def _latest_ok(rows: list[AgentDecision] | None) -> AgentDecision | None:
    if not rows:
        return None
    return next((d for d in reversed(rows) if d.status == "ok"), None)


def _first_ok(rows: list[AgentDecision] | None) -> AgentDecision | None:
    if not rows:
        return None
    return next((d for d in rows if d.status == "ok"), None)


def _pr_deployment(
    pr: PullRequest, deployments_by_source: dict[str, list[Deployment]]
) -> Deployment | None:
    """Which deployment shipped this merged PR, derived without a stored PR<->Deployment link.

    The synthetic generator deploys strictly in date order and never skips a pending merged PR
    (see sdlc/synth.py's _deploy): every deploy clears everything merged since the last one, in
    one batch, and batches never reorder or overlap. So the earliest same-source deployment at or
    after the PR's merge time is, deterministically, the one that shipped it. A PR merged after
    the last deploy correctly has none yet, and stays in Merged.
    """
    if pr.merged_at is None:
        return None
    candidates = [
        d for d in deployments_by_source.get(pr.source, []) if d.deployed_at >= pr.merged_at
    ]
    return min(candidates, key=lambda d: d.deployed_at) if candidates else None


def _owner(
    issue: Issue | None, pr: PullRequest | None, engineers: dict[int, Engineer]
) -> str | None:
    for person_id in (issue.assignee_id if issue else None, pr.author_id if pr else None):
        if person_id and person_id in engineers:
            return engineers[person_id].name
    return None


def _current_sprint(db: Session, today: date) -> Sprint | None:
    return db.scalar(
        select(Sprint).where(Sprint.start_date <= today, Sprint.end_date >= today).limit(1)
    )


def build_board(
    db: Session,
    *,
    now: datetime | None = None,
    sprint: str | None = None,
    module: str | None = None,
    owner: str | None = None,
    source: str | None = None,  # "synthetic" | "github" | None for both
) -> Board:
    now = now or datetime.now().replace(microsecond=0)
    engineers = {e.id: e for e in db.scalars(select(Engineer))}
    triage_decisions = _decisions_by_subject(db, TRIAGE_AGENT)
    risk_decisions = _decisions_by_subject(db, PR_RISK_AGENT)
    gate_by_pr = {g.pull_request_id: g for g in db.scalars(select(GateStatus))}
    deployments_by_source: dict[str, list[Deployment]] = defaultdict(list)
    for d in db.scalars(select(Deployment)):
        deployments_by_source[d.source].append(d)
    current_sprint = _current_sprint(db, now.date())

    sprints_by_id = {s.id: s for s in db.scalars(select(Sprint))}
    prs_by_issue: dict[int, list[PullRequest]] = defaultdict(list)
    standalone_prs: list[PullRequest] = []
    for pr in db.scalars(select(PullRequest)):
        (prs_by_issue[pr.issue_id].append(pr) if pr.issue_id else standalone_prs.append(pr))

    cards: list[Card] = []
    for issue in db.scalars(select(Issue)):
        linked = prs_by_issue.get(issue.id, [])
        if issue.state != "open" and not linked:
            continue  # closed with no PR: dropped out of the pipeline, never shipped
        card = _issue_card(
            issue,
            linked,
            now,
            engineers,
            sprints_by_id,
            triage_decisions,
            risk_decisions,
            gate_by_pr,
            deployments_by_source,
            current_sprint,
        )
        if card:
            cards.append(card)
    for pr in standalone_prs:
        card = _pr_card(
            pr, now, engineers, risk_decisions, gate_by_pr, deployments_by_source, current_sprint
        )
        if card:
            cards.append(card)

    # A card with no sprint (every real card, since nothing assigns one) is never excluded by a
    # sprint filter — real, live-demo work should always be visible regardless of which sprint
    # is selected. Only synthetic cards, which do carry a sprint, are actually filtered.
    if sprint and sprint != "all":
        target = current_sprint.name if sprint == "current" and current_sprint else sprint
        cards = [c for c in cards if c.sprint is None or c.sprint == target]
    if module:
        cards = [c for c in cards if c.module == module]
    if owner:
        cards = [c for c in cards if c.owner == owner]
    if source:
        cards = [c for c in cards if c.source == source]

    return Board(cards=tuple(cards), columns=_column_stats(cards, now), generated_at=now)


def _issue_card(
    issue: Issue,
    linked: list[PullRequest],
    now: datetime,
    engineers: dict[int, Engineer],
    sprints_by_id: dict[int, Sprint],
    triage_decisions,
    risk_decisions,
    gate_by_pr,
    deployments_by_source,
    current_sprint: Sprint | None,
) -> Card | None:
    sprint_name = sprints_by_id[issue.sprint_id].name if issue.sprint_id else None
    triage_ok = _first_ok(triage_decisions.get((issue.source, issue.number)))
    triaged = issue.module is not None and issue.estimate_points is not None
    # Synthetic issues carry module/points from birth (they never go through the triage agent),
    # so there's no decision to time the transition by; treat them as triaged from creation.
    triaged_at = triage_ok.created_at if triage_ok else issue.created_at
    transitions: list[tuple[str, datetime]] = [("backlog", issue.created_at)]
    if triaged:
        transitions.append(("triaged", triaged_at))

    best_pr, best_state = None, None
    for pr in linked:
        state = _pr_state(
            pr, now, risk_decisions, gate_by_pr, deployments_by_source, current_sprint
        )
        if state and (best_state is None or _RANK[state[0]] > _RANK[best_state[0]]):
            best_pr, best_state = pr, state

    if best_state is None:
        column, entered = ("triaged", triaged_at) if triaged else ("backlog", issue.created_at)
        decisions = (_to_decision(triage_ok),) if triage_ok else ()
        return Card(
            key=f"issue-{issue.number}",
            source=issue.source,
            issue_number=issue.number,
            pr_number=None,
            title=issue.title,
            module=issue.module,
            points=issue.estimate_points,
            owner=_owner(issue, None, engineers),
            column=column,
            entered_column_at=entered,
            sprint=sprint_name,
            decisions=decisions,
            transitions=tuple(transitions),
        )

    column, entered, tier, score, missing, rolled_back, pr_transitions = best_state
    transitions += pr_transitions
    risk_ok = _latest_ok(risk_decisions.get((best_pr.source, best_pr.number)))
    decisions = tuple(d for d in (triage_ok, risk_ok) if d)
    return Card(
        key=f"issue-{issue.number}",
        source=issue.source,
        issue_number=issue.number,
        pr_number=best_pr.number,
        title=issue.title,
        module=issue.module or best_pr.module,
        points=issue.estimate_points,
        owner=_owner(issue, best_pr, engineers),
        column=column,
        entered_column_at=entered,
        sprint=sprint_name,
        tier=tier,
        risk_score=score,
        gate_missing=missing,
        rolled_back=rolled_back,
        decisions=tuple(_to_decision(d) for d in decisions),
        transitions=tuple(transitions),
    )


def _pr_card(
    pr: PullRequest,
    now,
    engineers,
    risk_decisions,
    gate_by_pr,
    deployments_by_source,
    current_sprint,
) -> Card | None:
    state = _pr_state(pr, now, risk_decisions, gate_by_pr, deployments_by_source, current_sprint)
    if state is None:
        return None
    column, entered, tier, score, missing, rolled_back, transitions = state
    risk_ok = _latest_ok(risk_decisions.get((pr.source, pr.number)))
    return Card(
        key=f"pr-{pr.number}",
        source=pr.source,
        issue_number=None,
        pr_number=pr.number,
        title=pr.title,
        module=pr.module,
        points=None,
        owner=_owner(None, pr, engineers),
        column=column,
        entered_column_at=entered,
        tier=tier,
        risk_score=score,
        gate_missing=missing,
        rolled_back=rolled_back,
        decisions=(_to_decision(risk_ok),) if risk_ok else (),
        transitions=tuple(transitions),
    )


def _pr_state(
    pr: PullRequest, now, risk_decisions, gate_by_pr, deployments_by_source, current_sprint
):
    """(column, entered_at, tier, score, gate_missing, rolled_back, transitions) for one PR, or
    None if this PR contributes nothing (shouldn't happen for an open or merged PR, but a closed,
    never-merged PR is treated the same as a dropped issue: it leaves the board)."""
    if pr.state == "closed":
        return None

    transitions: list[tuple[str, datetime]] = []
    in_sprint = pr.source != "synthetic" or (
        current_sprint is not None
        and pr.created_at.date() >= current_sprint.start_date
        and pr.created_at.date() <= current_sprint.end_date
    )
    if in_sprint:
        transitions.append(("in_progress", pr.created_at))
    column, entered = ("in_progress", pr.created_at) if in_sprint else (None, None)

    risk_ok = _latest_ok(risk_decisions.get((pr.source, pr.number)))
    gate = gate_by_pr.get(pr.id)
    # gate.tier is set even when the agent failed (the fallback/floor tier) — a better answer
    # than "no tier at all" for a PR that's Gated because scoring itself broke.
    tier = risk_ok.tier if risk_ok else (gate.tier if gate else None)
    score = risk_ok.final_score if risk_ok else None
    missing = tuple(gate.missing) if gate else ()

    if risk_ok:
        column, entered = "in_review", risk_ok.created_at
        transitions.append(("in_review", risk_ok.created_at))
    if gate and gate.state in ("pending", "failure"):
        column, entered = "gated", gate.updated_at
        transitions.append(("gated", gate.updated_at))

    if pr.state == "merged" and pr.merged_at:
        column, entered = "merged", pr.merged_at
        transitions.append(("merged", pr.merged_at))
        deployment = _pr_deployment(pr, deployments_by_source)
        if deployment:
            column, entered = "production", deployment.deployed_at
            transitions.append(("production", deployment.deployed_at))
            return (
                column,
                entered,
                tier,
                score,
                missing,
                deployment.status == "rolled_back",
                transitions,
            )

    if column is None:
        return None
    return column, entered, tier, score, missing, False, transitions


def _to_decision(d: AgentDecision) -> Decision:
    return Decision(
        id=d.id,
        agent=d.agent,
        created_at=d.created_at,
        tier=d.tier,
        final_score=d.final_score,
        signals=d.signals,
        human_override=d.human_override,
    )


def serialize(board: Board) -> dict:
    """Board -> plain JSON-safe dict, the same shape metrics.py's functions return."""

    def decision(d: Decision) -> dict:
        return {
            "id": d.id,
            "agent": d.agent,
            "created_at": d.created_at.isoformat(),
            "tier": d.tier,
            "final_score": d.final_score,
            "signals": d.signals,
            "human_override": d.human_override,
        }

    def card(c: Card) -> dict:
        return {
            "key": c.key,
            "source": c.source,
            "issue_number": c.issue_number,
            "pr_number": c.pr_number,
            "title": c.title,
            "module": c.module,
            "points": c.points,
            "owner": c.owner,
            "sprint": c.sprint,
            "column": c.column,
            "entered_column_at": c.entered_column_at.isoformat(),
            "tier": c.tier,
            "risk_score": c.risk_score,
            "gate_missing": list(c.gate_missing),
            "rolled_back": c.rolled_back,
            "decisions": [decision(d) for d in c.decisions],
            "transitions": [[name, at.isoformat()] for name, at in c.transitions],
        }

    return {
        "generated_at": board.generated_at.isoformat(),
        "columns": board.columns,
        "cards": [card(c) for c in board.cards],
    }


def _column_stats(cards: list[Card], now: datetime) -> dict:
    by_column: dict[str, list[Card]] = defaultdict(list)
    for c in cards:
        by_column[c.column].append(c)
    out = {}
    for name in COLUMNS:
        items = by_column.get(name, [])
        ages = [(now - c.entered_column_at).total_seconds() / 3600 for c in items]
        out[name] = {
            "title": COLUMN_TITLES[name],
            "wip": len(items),
            "median_age_hours": round(median(ages), 1) if ages else None,
        }
    return out
