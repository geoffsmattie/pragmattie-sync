"""The risk-gate's current, queryable state per PR: a read model, not an audit trail.

Revision ID: 0005_gate_status
Revises: 0004_agent_decisions
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_gate_status"
down_revision: str | None = "0004_agent_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sdlc_gate_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pull_request_id", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=2), nullable=True),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("would_be", sa.String(length=10), nullable=False),
        sa.Column("missing", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=140), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pull_request_id"],
            ["sdlc_pull_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # unique=True, index=True on the model's column renders as one unique index, not a
    # separate UniqueConstraint plus a plain index — match that exactly or `alembic check`
    # sees drift.
    op.create_index(
        op.f("ix_sdlc_gate_status_pull_request_id"),
        "sdlc_gate_status",
        ["pull_request_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_sdlc_gate_status_updated_at"), "sdlc_gate_status", ["updated_at"], unique=False
    )


def downgrade() -> None:
    # Dropping the table drops its indexes; MySQL won't drop an index a foreign key needs.
    op.drop_table("sdlc_gate_status")
