"""File facts on pull requests: test files changed, docs-only, modules touched.

Revision ID: 0003_pr_file_facts
Revises: 0002_sdlc_approvals
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_pr_file_facts"
down_revision: str | None = "0002_sdlc_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows get neutral values; re-run the collector or `sdlc.synth --reset` to fill them.
    with op.batch_alter_table("sdlc_pull_requests") as batch:
        batch.add_column(
            sa.Column("test_files_changed", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("docs_only", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("modules_touched", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("sdlc_pull_requests") as batch:
        batch.drop_column("modules_touched")
        batch.drop_column("docs_only")
        batch.drop_column("test_files_changed")
