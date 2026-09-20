"""SDLC signal tables: engineers, sprints, issues, PRs, CI runs, deployments, incidents.

Revision ID: 0001_sdlc_signals
Revises:
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_sdlc_signals"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdlc_deployments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("deployed_at", sa.DateTime(), nullable=False),
        sa.Column("pr_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sdlc_deployments_deployed_at"), "sdlc_deployments", ["deployed_at"], unique=False
    )
    op.create_index(
        op.f("ix_sdlc_deployments_source"), "sdlc_deployments", ["source"], unique=False
    )
    op.create_table(
        "sdlc_engineers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=60), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "login"),
    )
    op.create_table(
        "sdlc_sprints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("goal", sa.String(length=200), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sdlc_sprints_start_date"), "sdlc_sprints", ["start_date"], unique=False
    )
    op.create_table(
        "sdlc_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("module", sa.String(length=30), nullable=True),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=True),
        sa.Column("estimate_points", sa.Integer(), nullable=True),
        sa.Column("actual_days", sa.Float(), nullable=True),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("sprint_id", sa.Integer(), nullable=True),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["sdlc_engineers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["sprint_id"],
            ["sdlc_sprints.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id"),
    )
    op.create_index(op.f("ix_sdlc_issues_created_at"), "sdlc_issues", ["created_at"], unique=False)
    op.create_index(op.f("ix_sdlc_issues_module"), "sdlc_issues", ["module"], unique=False)
    op.create_index(op.f("ix_sdlc_issues_source"), "sdlc_issues", ["source"], unique=False)
    op.create_table(
        "sdlc_pull_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("module", sa.String(length=30), nullable=True),
        sa.Column("files_changed", sa.Integer(), nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("touches_migration", sa.Boolean(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("first_review_hours", sa.Float(), nullable=True),
        sa.Column("rework_commits", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("merged_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("caused_incident", sa.Boolean(), nullable=False),
        sa.Column("reverted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["sdlc_engineers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["sdlc_issues.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id"),
    )
    op.create_index(
        op.f("ix_sdlc_pull_requests_created_at"), "sdlc_pull_requests", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_sdlc_pull_requests_module"), "sdlc_pull_requests", ["module"], unique=False
    )
    op.create_index(
        op.f("ix_sdlc_pull_requests_source"), "sdlc_pull_requests", ["source"], unique=False
    )
    op.create_table(
        "sdlc_ci_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("pull_request_id", sa.Integer(), nullable=True),
        sa.Column("suite", sa.String(length=40), nullable=False),
        sa.Column("conclusion", sa.String(length=20), nullable=False),
        sa.Column("flaky", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["sdlc_pull_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id"),
    )
    op.create_index(op.f("ix_sdlc_ci_runs_source"), "sdlc_ci_runs", ["source"], unique=False)
    op.create_index(
        op.f("ix_sdlc_ci_runs_started_at"), "sdlc_ci_runs", ["started_at"], unique=False
    )
    op.create_index(op.f("ix_sdlc_ci_runs_suite"), "sdlc_ci_runs", ["suite"], unique=False)
    op.create_table(
        "sdlc_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("module", sa.String(length=30), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("caused_by_pr_id", sa.Integer(), nullable=True),
        sa.Column("deployment_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["caused_by_pr_id"],
            ["sdlc_pull_requests.id"],
        ),
        sa.ForeignKeyConstraint(
            ["deployment_id"],
            ["sdlc_deployments.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sdlc_incidents_opened_at"), "sdlc_incidents", ["opened_at"], unique=False
    )
    op.create_index(op.f("ix_sdlc_incidents_source"), "sdlc_incidents", ["source"], unique=False)


def downgrade() -> None:
    # Dropping a table drops its indexes; MySQL won't drop an index a foreign key needs.
    for table in (
        "sdlc_incidents",
        "sdlc_ci_runs",
        "sdlc_pull_requests",
        "sdlc_issues",
        "sdlc_sprints",
        "sdlc_engineers",
        "sdlc_deployments",
    ):
        op.drop_table(table)
