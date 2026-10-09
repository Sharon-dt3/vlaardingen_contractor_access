"""Merge concurrent invitation-workflow migration heads.

Revision ID: 20260923_0009
Revises: 20260922_0008, 20260923_0008
Create Date: 2026-09-23
"""

from typing import Sequence


revision: str = "20260923_0009"
down_revision: tuple[str, str] = ("20260922_0008", "20260923_0008")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration history; both parent revisions own their schema changes."""


def downgrade() -> None:
    """Split migration history; neither parent schema change is reverted here."""
