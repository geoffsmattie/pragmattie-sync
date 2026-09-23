"""Issues carry the epic they belong to, so epics can be forecast.

Revision ID: 0006_issue_epic
Revises: 0005_gate_status
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_issue_epic"
down_revision: str | None = "0005_gate_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sdlc_issues", sa.Column("epic", sa.String(length=80), nullable=True))
    op.create_index(op.f("ix_sdlc_issues_epic"), "sdlc_issues", ["epic"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sdlc_issues_epic"), table_name="sdlc_issues")
    op.drop_column("sdlc_issues", "epic")
