"""Real deployments and incidents from GitHub, and the merge commit of each real PR.

The release gate (sdlc/release_runner.py) needs to know which commit a real deployment shipped
and which merged PRs that covers, and to read incidents raised as GitHub issues. Simulated rows
leave the new columns empty.

Revision ID: 0008_release_gate
Revises: 0007_forecasts
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_release_gate"
down_revision: str | None = "0007_forecasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sdlc_pull_requests", sa.Column("merge_commit_sha", sa.String(length=40), nullable=True)
    )
    for table in ("sdlc_deployments", "sdlc_incidents"):
        op.add_column(table, sa.Column("external_id", sa.String(length=64), nullable=True))
        op.create_unique_constraint(
            f"uq_{table}_source_external_id", table, ["source", "external_id"]
        )
    op.add_column("sdlc_deployments", sa.Column("sha", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("sdlc_deployments", "sha")
    for table in ("sdlc_deployments", "sdlc_incidents"):
        op.drop_constraint(f"uq_{table}_source_external_id", table, type_="unique")
        op.drop_column(table, "external_id")
    op.drop_column("sdlc_pull_requests", "merge_commit_sha")
