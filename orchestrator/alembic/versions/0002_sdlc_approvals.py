"""Approvals owed to pull requests by a simulated approver.

Revision ID: 0002_sdlc_approvals
Revises: 0001_sdlc_signals
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sdlc_approvals"
down_revision: str | None = "0001_sdlc_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdlc_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("pull_request_id", sa.Integer(), nullable=False),
        sa.Column("approver_id", sa.String(length=60), nullable=False),
        sa.Column("tier", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["sdlc_pull_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pull_request_id", "approver_id"),
    )
    op.create_index(
        op.f("ix_sdlc_approvals_pull_request_id"),
        "sdlc_approvals",
        ["pull_request_id"],
        unique=False,
    )
    op.create_index(op.f("ix_sdlc_approvals_status"), "sdlc_approvals", ["status"], unique=False)


def downgrade() -> None:
    # Dropping the table drops its indexes; MySQL won't drop an index a foreign key needs.
    op.drop_table("sdlc_approvals")
