"""Persist invitation delivery and single-use email response state.

Revision ID: 20260925_0010
Revises: 20260923_0009
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260925_0010"
down_revision: str | None = "20260923_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Add invitation response metadata without modifying existing workflows."""

    op.add_column(
        "invitations",
        sa.Column("response_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "invitations",
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column("delivery_status", sa.String(24), nullable=False, server_default="local_only"),
    )
    op.add_column(
        "invitations",
        sa.Column("response_token_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column("response_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_invitations_response_token_hash",
        "invitations",
        ["response_token_hash"],
        unique=True,
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove invitation email-response metadata."""

    op.drop_index("ix_invitations_response_token_hash", table_name="invitations")
    for column in (
        "response_token_expires_at",
        "response_token_hash",
        "delivery_status",
        "responded_at",
        "response_status",
    ):
        op.drop_column("invitations", column)
