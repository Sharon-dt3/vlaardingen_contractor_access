"""Create the Batch 0 foundation state table.

Revision ID: 20260922_0001
Revises:
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260922_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the deterministic foundation seed marker table."""

    op.create_table(
        "foundation_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("seed_version", sa.String(length=32), nullable=False),
        sa.Column("seeded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Remove the deterministic foundation seed marker table."""

    op.drop_table("foundation_state")
