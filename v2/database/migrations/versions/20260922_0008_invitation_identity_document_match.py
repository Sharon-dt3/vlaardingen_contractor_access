"""Add private invitation identity-document metadata for gate matching.

Revision ID: 20260922_0008
Revises: 20260922_0007
Create Date: 2026-09-23
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260922_0008"
down_revision: str | None = "20260922_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add private document-reference metadata to invitations."""

    op.add_column(
        "invitations",
        sa.Column("identity_document_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column(
            "identity_document_storage_reference",
            sa.String(length=160),
            nullable=True,
        ),
    )
    op.add_column(
        "invitations",
        sa.Column(
            "identity_document_media_type",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "invitations",
        sa.Column(
            "identity_document_uploaded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove invitation identity-document matching metadata."""

    op.drop_column("invitations", "identity_document_uploaded_at")
    op.drop_column("invitations", "identity_document_media_type")
    op.drop_column("invitations", "identity_document_storage_reference")
    op.drop_column("invitations", "identity_document_sha256")
