"""CRM core tables: reps, accounts, contacts, leads, opportunities.

Revision ID: 0002_crm_core
Revises: 0001_baseline
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_crm_core"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False),
        sa.Column("quarterly_quota", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=False),
        sa.Column("employee_count", sa.Integer(), nullable=False),
        sa.Column("annual_revenue", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False),
        sa.Column("website", sa.String(length=200), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["reps.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_accounts_name"), "accounts", ["name"], unique=False)
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contacts_account_id"), "contacts", ["account_id"], unique=False)
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("converted_account_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["converted_account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["reps.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_leads_email"), "leads", ["email"], unique=False)
    op.create_index(op.f("ix_leads_status"), "leads", ["status"], unique=False)
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("probability", sa.Integer(), nullable=False),
        sa.Column("close_date", sa.Date(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["reps.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_opportunities_account_id"), "opportunities", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_opportunities_close_date"), "opportunities", ["close_date"], unique=False
    )
    op.create_index(op.f("ix_opportunities_stage"), "opportunities", ["stage"], unique=False)


def downgrade() -> None:
    # Dropping a table drops its indexes too. (MySQL refuses to drop an index that a
    # foreign key still needs, so indexes are not dropped one by one.)
    for table in ("opportunities", "leads", "contacts", "accounts", "reps"):
        op.drop_table(table)
