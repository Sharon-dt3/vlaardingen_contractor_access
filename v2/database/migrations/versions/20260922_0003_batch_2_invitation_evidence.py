"""Create Batch 2 invitation, registration, and evidence persistence.

Revision ID: 20260922_0003
Revises: 20260922_0002
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0003"
down_revision: str | None = "20260922_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

invitation_population = sa.Enum(
    "RENEWI_DRIVER",
    "TEMPORARY_DRIVER",
    "EXTERNAL_DRIVER",
    "MAINTENANCE_CONTRACTOR",
    "PERMANENT_CONTRACTOR",
    "VISITOR",
    name="invitation_population",
    native_enum=False,
    create_constraint=True,
)
invitation_status = sa.Enum(
    "INVITED",
    "PRE_REGISTERED",
    "EVIDENCE_READY",
    name="invitation_status",
    native_enum=False,
    create_constraint=True,
)
evidence_type = sa.Enum(
    "ID_CARD",
    "DRIVING_LICENCE",
    "VCA_CERTIFICATE",
    "INSURANCE_CERTIFICATE",
    name="evidence_type",
    native_enum=False,
    create_constraint=True,
)
evidence_status = sa.Enum(
    "UPLOADED",
    "EXTRACTED",
    "VERIFIED",
    "REJECTED",
    "REUPLOAD_REQUESTED",
    "SUPERSEDED",
    name="evidence_status",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Create constrained invitation, synthetic-asset, and evidence tables."""

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.String(length=64), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitee_email", sa.String(length=254), nullable=False),
        sa.Column("population", invitation_population, nullable=False),
        sa.Column("company_name", sa.String(length=180), nullable=False),
        sa.Column("purpose", sa.String(length=240), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", invitation_status, nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_invitations_window"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["people.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["user_accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", name="uq_invitations_seed_key"),
        sa.UniqueConstraint("visit_id"),
    )
    op.create_index("ix_invitations_site_id", "invitations", ["site_id"])
    op.create_index(
        "ix_invitations_requested_by_id", "invitations", ["requested_by_id"]
    )
    op.create_index("ix_invitations_person_id", "invitations", ["person_id"])
    op.create_index("ix_invitations_status", "invitations", ["status"])

    op.create_table(
        "evidence_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_key", sa.String(length=80), nullable=False),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("display_name", sa.String(length=180), nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_reference", sa.String(length=160), nullable=False),
        sa.Column("expected_fields", sa.JSON(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_key", name="uq_evidence_assets_asset_key"),
    )
    op.create_index(
        "ix_evidence_assets_type", "evidence_assets", ["evidence_type"]
    )

    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("status", evidence_status, nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_reference", sa.String(length=160), nullable=False),
        sa.Column("storage_mode", sa.String(length=16), nullable=False),
        sa.Column("provider_mode", sa.String(length=16), nullable=False),
        sa.Column("extracted_fields", sa.JSON(), nullable=False),
        sa.Column("field_confidence", sa.JSON(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date",
            name="ck_evidence_date_order",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["evidence_assets.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["invitations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["people.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], ["evidence.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"], ["user_accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_person_id", "evidence", ["person_id"])
    op.create_index("ix_evidence_invitation_id", "evidence", ["invitation_id"])
    op.create_index("ix_evidence_status", "evidence", ["status"])
    op.create_index("ix_evidence_expiry_date", "evidence", ["expiry_date"])


def downgrade() -> None:
    """Remove Batch 2 records while retaining the Batch 1 schema."""

    op.drop_index("ix_evidence_expiry_date", table_name="evidence")
    op.drop_index("ix_evidence_status", table_name="evidence")
    op.drop_index("ix_evidence_invitation_id", table_name="evidence")
    op.drop_index("ix_evidence_person_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_evidence_assets_type", table_name="evidence_assets")
    op.drop_table("evidence_assets")
    op.drop_index("ix_invitations_status", table_name="invitations")
    op.drop_index("ix_invitations_person_id", table_name="invitations")
    op.drop_index("ix_invitations_requested_by_id", table_name="invitations")
    op.drop_index("ix_invitations_site_id", table_name="invitations")
    op.drop_table("invitations")
