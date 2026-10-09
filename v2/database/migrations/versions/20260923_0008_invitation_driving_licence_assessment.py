"""Persist reviewable Dutch driving-licence validity assessments.

Revision ID: 20260923_0008
Revises: 20260922_0007
Create Date: 2026-09-23
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260923_0008"
down_revision: str | None = "20260922_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a server-generated review assessment to private evidence metadata."""

    op.add_column(
        "evidence",
        sa.Column(
            "validity_assessment",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column("evidence", "validity_assessment", server_default=None)


def downgrade() -> None:
    """Remove the persisted assessment while preserving evidence records."""

    op.drop_column("evidence", "validity_assessment")
