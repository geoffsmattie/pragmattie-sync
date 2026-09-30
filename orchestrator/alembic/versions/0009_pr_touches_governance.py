"""Whether a pull request touches governance files (CI workflows, policies), for the T2 floor.

Revision ID: 0009_pr_touches_governance
Revises: 0008_release_gate
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_pr_touches_governance"
down_revision: str | None = "0008_release_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows get false; the collector fills real PRs in on its next run.
    with op.batch_alter_table("sdlc_pull_requests") as batch:
        batch.add_column(
            sa.Column("touches_governance", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("sdlc_pull_requests") as batch:
        batch.drop_column("touches_governance")
