"""Create Batch 6 demo-time, expiry-alert, and re-validation persistence.

Revision ID: 20260922_0007
Revises: 20260922_0006
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260922_0007"
down_revision: str | None = "20260922_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


expiry_subject_kind = sa.Enum(
    "EVIDENCE",
    "TRAINING",
    name="expiry_subject_kind",
    native_enum=False,
    create_constraint=True,
)
revalidation_task_status = sa.Enum(
    "OPEN",
    "COMPLETED",
    name="revalidation_task_status",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Create persisted effective time, idempotent alerts, and renewal tasks."""

    op.create_table(
        "demo_clock",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_demo_clock_singleton_id"),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "expiry_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", expiry_subject_kind, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_code", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_mode", sa.String(length=32), nullable=False),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("provider_reference", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["compliance_requirements.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_kind",
            "source_id",
            "alert_code",
            name="uq_expiry_alerts_source_code",
        ),
    )
    op.create_index("ix_expiry_alerts_person_id", "expiry_alerts", ["person_id"])
    op.create_index("ix_expiry_alerts_requirement_id", "expiry_alerts", ["requirement_id"])
    op.create_index("ix_expiry_alerts_site_id", "expiry_alerts", ["site_id"])
    op.create_index("ix_expiry_alerts_created_at", "expiry_alerts", ["created_at"])

    op.create_table(
        "revalidation_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", expiry_subject_kind, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", revalidation_task_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["compliance_requirements.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "requirement_id",
            "source_kind",
            "source_id",
            name="uq_revalidation_tasks_source",
        ),
    )
    op.create_index(
        "ix_revalidation_tasks_person_id",
        "revalidation_tasks",
        ["person_id"],
    )
    op.create_index(
        "ix_revalidation_tasks_site_id",
        "revalidation_tasks",
        ["site_id"],
    )
    op.create_index(
        "ix_revalidation_tasks_status",
        "revalidation_tasks",
        ["status"],
    )
    op.create_index(
        "ix_revalidation_tasks_requirement_id",
        "revalidation_tasks",
        ["requirement_id"],
    )


def downgrade() -> None:
    """Remove Batch 6 persistence while retaining prior batch records."""

    op.drop_index(
        "ix_revalidation_tasks_requirement_id",
        table_name="revalidation_tasks",
    )
    op.drop_index("ix_revalidation_tasks_status", table_name="revalidation_tasks")
    op.drop_index("ix_revalidation_tasks_site_id", table_name="revalidation_tasks")
    op.drop_index("ix_revalidation_tasks_person_id", table_name="revalidation_tasks")
    op.drop_table("revalidation_tasks")

    op.drop_index("ix_expiry_alerts_created_at", table_name="expiry_alerts")
    op.drop_index("ix_expiry_alerts_site_id", table_name="expiry_alerts")
    op.drop_index("ix_expiry_alerts_requirement_id", table_name="expiry_alerts")
    op.drop_index("ix_expiry_alerts_person_id", table_name="expiry_alerts")
    op.drop_table("expiry_alerts")
    op.drop_table("demo_clock")
