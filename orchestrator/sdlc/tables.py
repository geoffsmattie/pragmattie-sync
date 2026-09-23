"""Engineering activity ("signals") the prediction models learn from.

Every row records where it came from in `source`:
  synthetic  generated history (see sdlc/synth.py), clearly labelled in the UI
  github     collected from the real repository (see sdlc/signals/github.py)
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sdlc.db import Base

MODULES = (
    "leads",
    "accounts",
    "pipeline",
    "forecasting",
    "integrations",
    "billing_auth",
    "orchestrator",
    "platform",
)
SOURCES = ("synthetic", "github")


class Engineer(Base):
    __tablename__ = "sdlc_engineers"
    __table_args__ = (UniqueConstraint("source", "login"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(20), default="synthetic")


class Sprint(Base):
    __tablename__ = "sdlc_sprints"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date)
    goal: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="synthetic")


class Issue(Base):
    __tablename__ = "sdlc_issues"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="synthetic", index=True)
    external_id: Mapped[str | None] = mapped_column(String(64))
    number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    module: Mapped[str | None] = mapped_column(String(30), index=True)
    type: Mapped[str] = mapped_column(String(20), default="feature")  # feature | bug | chore
    priority: Mapped[str | None] = mapped_column(String(10))  # p1 | p2 | p3
    estimate_points: Mapped[int | None] = mapped_column(Integer)
    actual_days: Mapped[float | None] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_sprints.id"))
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_engineers.id"))
    # The epic this story belongs to, by name (an `epic:<name>` label on a real issue). Epics
    # are forecast on their own, so a story added to one live moves that epic's date.
    epic: Mapped[str | None] = mapped_column(String(80), index=True)

    assignee: Mapped[Engineer | None] = relationship()


class PullRequest(Base):
    __tablename__ = "sdlc_pull_requests"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="synthetic", index=True)
    external_id: Mapped[str | None] = mapped_column(String(64))
    number: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_engineers.id"))
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_issues.id"))
    module: Mapped[str | None] = mapped_column(String(30), index=True)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    touches_migration: Mapped[bool] = mapped_column(Boolean, default=False)
    # File facts the risk score reads (see sdlc/changes.py).
    test_files_changed: Mapped[int] = mapped_column(Integer, default=0)
    docs_only: Mapped[bool] = mapped_column(Boolean, default=False)
    modules_touched: Mapped[int] = mapped_column(Integer, default=1)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    first_review_hours: Mapped[float | None] = mapped_column(Float)
    rework_commits: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(10), default="open")  # open | merged | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Outcome labels the PR risk model learns to predict (Phase 4).
    caused_incident: Mapped[bool] = mapped_column(Boolean, default=False)
    reverted: Mapped[bool] = mapped_column(Boolean, default=False)

    author: Mapped[Engineer | None] = relationship()


class CIRun(Base):
    __tablename__ = "sdlc_ci_runs"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="synthetic", index=True)
    external_id: Mapped[str | None] = mapped_column(String(64))
    pull_request_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_pull_requests.id"))
    suite: Mapped[str] = mapped_column(String(40), index=True)
    conclusion: Mapped[str] = mapped_column(String(20))  # success | failure | cancelled
    flaky: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)


class Deployment(Base):
    __tablename__ = "sdlc_deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="synthetic", index=True)
    version: Mapped[str] = mapped_column(String(40))
    deployed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    pr_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")  # success | rolled_back


class Incident(Base):
    __tablename__ = "sdlc_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="synthetic", index=True)
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10))  # sev1 | sev2 | sev3
    module: Mapped[str | None] = mapped_column(String(30))
    opened_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    caused_by_pr_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_pull_requests.id"))
    deployment_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_deployments.id"))


class Approval(Base):
    """A governance approval a simulated approver owes a pull request (see sdlc/approver.py).

    `source` is always "simulated": the approver stands in for a second human, so the UI and
    audit log must never present these as real human approvals.
    """

    __tablename__ = "sdlc_approvals"
    __table_args__ = (UniqueConstraint("pull_request_id", "approver_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), default="simulated")
    pull_request_id: Mapped[int] = mapped_column(ForeignKey("sdlc_pull_requests.id"), index=True)
    approver_id: Mapped[str] = mapped_column(String(60))  # id in policies/approvers.yaml
    tier: Mapped[str] = mapped_column(String(2))  # T0 | T1 | T2 | T3
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # | approved
    reason: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(String(300))
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)

    pull_request: Mapped[PullRequest] = relationship()


class AgentDecision(Base):
    """One row per agent run: what it saw, what it decided and what it did about it.

    Append-only. Nothing is updated in place; a correction is a new row whose `supersedes_id`
    points at the one it replaces. Written in the same transaction as the action it records.
    """

    __tablename__ = "sdlc_agent_decisions"
    # One decision per (agent, subject, commit, attempt): a failed run may be retried, and each
    # retry is its own row, but the same attempt can never be recorded twice.
    __table_args__ = (
        UniqueConstraint(
            "agent", "subject_type", "subject_source", "subject_id", "head_sha", "attempt"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)  # e.g. pr_risk
    agent_version: Mapped[str] = mapped_column(String(20))
    model_id: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    subject_type: Mapped[str] = mapped_column(String(10))  # pr | issue
    subject_source: Mapped[str] = mapped_column(String(20))  # synthetic | github
    subject_id: Mapped[int] = mapped_column(Integer, index=True)  # the PR or issue number
    head_sha: Mapped[str | None] = mapped_column(String(40))  # the commit scored
    attempt: Mapped[int] = mapped_column(Integer, default=1)  # 2, 3... after a failed run
    trigger: Mapped[str] = mapped_column(String(20))  # poll | schedule | manual
    inputs_digest: Mapped[dict | None] = mapped_column(JSON)
    raw_score: Mapped[int | None] = mapped_column(Integer)
    adjustment: Mapped[int | None] = mapped_column(Integer)  # the model's, kept separate
    final_score: Mapped[int | None] = mapped_column(Integer)
    tier: Mapped[str | None] = mapped_column(String(2))
    signals: Mapped[dict | None] = mapped_column(JSON)  # points per signal: the explanation
    output: Mapped[dict | None] = mapped_column(JSON)  # the agent's structured output, verbatim
    action_taken: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="ok", index=True)
    error: Mapped[str | None] = mapped_column(String(500))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    human_override: Mapped[dict | None] = mapped_column(JSON)  # tier before/after, actor, reason
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("sdlc_agent_decisions.id"))


class GateStatus(Base):
    """The risk-gate's current state for one PR: a read model, not an audit trail.

    The gate's "what it's waiting for" reasoning (sdlc/agents/gate.py's Gate) is computed fresh
    on every poll from live GitHub state (the sign-off tick-boxes, the simulated approval) and
    was previously thrown away once written to GitHub's status API. This table is the one place
    that reasoning is persisted, upserted by sdlc/runner.py every time it recomputes a PR's gate,
    so the delivery board (or anything else) can read "what's this PR waiting for" without an
    extra live GitHub call. One row per PR; a new poll replaces it, it is never appended to.
    """

    __tablename__ = "sdlc_gate_status"

    id: Mapped[int] = mapped_column(primary_key=True)
    pull_request_id: Mapped[int] = mapped_column(
        ForeignKey("sdlc_pull_requests.id"), unique=True, index=True
    )
    tier: Mapped[str | None] = mapped_column(String(2))
    state: Mapped[str] = mapped_column(String(10))  # success | pending | failure
    would_be: Mapped[str] = mapped_column(String(10))  # what enforce mode would post
    missing: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["human sign-off"]
    description: Mapped[str] = mapped_column(String(140))
    mode: Mapped[str] = mapped_column(String(10))  # shadow | enforce, when this was computed
    updated_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    pull_request: Mapped[PullRequest] = relationship()
