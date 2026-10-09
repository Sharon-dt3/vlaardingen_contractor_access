"""Create Batch 3 training, compliance, approval, and access-token persistence.

Revision ID: 20260922_0004
Revises: 20260922_0003
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0004"
down_revision: str | None = "20260922_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

training_outcome = sa.Enum(
    "PASSED",
    "FAILED",
    name="training_outcome",
    native_enum=False,
    create_constraint=True,
)
blacklist_subject_type = sa.Enum(
    "PERSON",
    "COMPANY",
    name="blacklist_subject_type",
    native_enum=False,
    create_constraint=True,
)
compliance_requirement_kind = sa.Enum(
    "EVIDENCE",
    "TRAINING",
    name="compliance_requirement_kind",
    native_enum=False,
    create_constraint=True,
)
approval_decision = sa.Enum(
    "PENDING",
    "APPROVED",
    "REJECTED",
    "CORRECTION_REQUESTED",
    "SUPERSEDED",
    name="approval_decision",
    native_enum=False,
    create_constraint=True,
)
access_token_status = sa.Enum(
    "ACTIVE",
    "REVOKED",
    "EXPIRED",
    name="access_token_status",
    native_enum=False,
    create_constraint=True,
)
compliance_population = sa.Enum(
    "RENEWI_DRIVER",
    "TEMPORARY_DRIVER",
    "EXTERNAL_DRIVER",
    "MAINTENANCE_CONTRACTOR",
    "PERMANENT_CONTRACTOR",
    "VISITOR",
    name="compliance_population",
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
    create_constraint=False,
)


def upgrade() -> None:
    """Create all durable tables required by Batch 3 domain commands."""

    op.create_table(
        "training_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("passing_score", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_training_modules_code"),
    )
    op.create_index(
        "ix_training_modules_active",
        "training_modules",
        ["is_active"],
    )

    op.create_table(
        "training_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "training_module_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("outcome", training_outcome, nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_training_results_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["training_module_id"],
            ["training_modules.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "training_module_id",
            "attempt_number",
            name="uq_training_results_attempt",
        ),
    )
    op.create_index(
        "ix_training_results_person_id",
        "training_results",
        ["person_id"],
    )
    op.create_index(
        "ix_training_results_module_id",
        "training_results",
        ["training_module_id"],
    )
    op.create_index(
        "ix_training_results_expires_at",
        "training_results",
        ["expires_at"],
    )

    op.create_table(
        "blacklist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", blacklist_subject_type, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revoked_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(person_id IS NOT NULL AND company_id IS NULL) OR "
            "(person_id IS NULL AND company_id IS NOT NULL)",
            name="ck_blacklist_entries_single_subject",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_blacklist_entries_person_id",
        "blacklist_entries",
        ["person_id"],
    )
    op.create_index(
        "ix_blacklist_entries_company_id",
        "blacklist_entries",
        ["company_id"],
    )
    op.create_index(
        "ix_blacklist_entries_active_window",
        "blacklist_entries",
        ["is_active", "starts_at", "ends_at"],
    )

    op.create_table(
        "compliance_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("population", compliance_population, nullable=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column(
            "requirement_kind",
            compliance_requirement_kind,
            nullable=False,
        ),
        sa.Column("evidence_type", evidence_type, nullable=True),
        sa.Column(
            "training_module_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "(requirement_kind = 'EVIDENCE' AND evidence_type IS NOT NULL "
            "AND training_module_id IS NULL) OR "
            "(requirement_kind = 'TRAINING' AND training_module_id IS NOT NULL "
            "AND evidence_type IS NULL)",
            name="ck_compliance_requirement_subject",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["training_module_id"],
            ["training_modules.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id",
            "population",
            "code",
            name="uq_compliance_requirements_site_population_code",
        ),
    )
    op.create_index(
        "ix_compliance_requirements_site_id",
        "compliance_requirements",
        ["site_id"],
    )
    op.create_index(
        "ix_compliance_requirements_active",
        "compliance_requirements",
        ["is_active"],
    )

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", approval_decision, nullable=False),
        sa.Column("compliance_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evaluated_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_by_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_visit_id", "approvals", ["visit_id"])
    op.create_index("ix_approvals_decision", "approvals", ["decision"])
    op.create_index("ix_approvals_decided_at", "approvals", ["decided_at"])

    op.create_table(
        "access_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_hash", sa.String(length=64), nullable=False),
        sa.Column("status", access_token_status, nullable=False),
        sa.Column("issued_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["issued_by_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reference_hash",
            name="uq_access_tokens_reference_hash",
        ),
    )
    op.create_index("ix_access_tokens_visit_id", "access_tokens", ["visit_id"])
    op.create_index("ix_access_tokens_status", "access_tokens", ["status"])
    op.create_index(
        "ix_access_tokens_expires_at",
        "access_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    """Remove Batch 3 persistence while preserving Batch 2 tables."""

    op.drop_index("ix_access_tokens_expires_at", table_name="access_tokens")
    op.drop_index("ix_access_tokens_status", table_name="access_tokens")
    op.drop_index("ix_access_tokens_visit_id", table_name="access_tokens")
    op.drop_table("access_tokens")
    op.drop_index("ix_approvals_decided_at", table_name="approvals")
    op.drop_index("ix_approvals_decision", table_name="approvals")
    op.drop_index("ix_approvals_visit_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(
        "ix_compliance_requirements_active",
        table_name="compliance_requirements",
    )
    op.drop_index(
        "ix_compliance_requirements_site_id",
        table_name="compliance_requirements",
    )
    op.drop_table("compliance_requirements")
    op.drop_index(
        "ix_blacklist_entries_active_window",
        table_name="blacklist_entries",
    )
    op.drop_index(
        "ix_blacklist_entries_company_id",
        table_name="blacklist_entries",
    )
    op.drop_index(
        "ix_blacklist_entries_person_id",
        table_name="blacklist_entries",
    )
    op.drop_table("blacklist_entries")
    op.drop_index(
        "ix_training_results_expires_at",
        table_name="training_results",
    )
    op.drop_index(
        "ix_training_results_module_id",
        table_name="training_results",
    )
    op.drop_index(
        "ix_training_results_person_id",
        table_name="training_results",
    )
    op.drop_table("training_results")
    op.drop_index(
        "ix_training_modules_active",
        table_name="training_modules",
    )
    op.drop_table("training_modules")
