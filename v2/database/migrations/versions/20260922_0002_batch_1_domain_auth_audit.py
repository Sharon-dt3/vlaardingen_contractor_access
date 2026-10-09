"""Create the Batch 1 domain, authentication, scenario, and audit schema.

Revision ID: 20260922_0002
Revises: 20260922_0001
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0002"
down_revision: str | None = "20260922_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

population = sa.Enum(
    "RENEWI_DRIVER",
    "TEMPORARY_DRIVER",
    "EXTERNAL_DRIVER",
    "MAINTENANCE_CONTRACTOR",
    "PERMANENT_CONTRACTOR",
    "VISITOR",
    name="population",
    native_enum=False,
    create_constraint=True,
)
person_standing = sa.Enum(
    "ACTIVE",
    "BLOCKED",
    "INACTIVE",
    name="person_standing",
    native_enum=False,
    create_constraint=True,
)
visit_status = sa.Enum(
    "PLANNED",
    "ACTIVE",
    "BLOCKED",
    "COMPLETED",
    "CANCELLED",
    name="visit_status",
    native_enum=False,
    create_constraint=True,
)
role = sa.Enum(
    "SYSTEM_ADMIN",
    "COMPLIANCE",
    "SITE_MANAGER",
    "GATE_OPERATOR",
    "HOST",
    "PARTICIPANT",
    "VIEWER",
    name="role",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Create constrained core records, accounts, scenarios, and audit events."""

    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("gate_mode", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("country_code IN ('NL', 'BE')", name="ck_sites_country"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", name="uq_sites_seed_key"),
    )
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("company_type", sa.String(length=48), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", name="uq_companies_seed_key"),
    )
    op.create_table(
        "people",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.String(length=64), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("population", population, nullable=False),
        sa.Column("standing", person_standing, nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", name="uq_people_seed_key"),
    )
    op.create_index("ix_people_company_id", "people", ["company_id"])
    op.create_index("ix_people_population", "people", ["population"])
    op.create_index("ix_people_standing", "people", ["standing"])

    op.create_table(
        "visits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.String(length=64), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host_person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(length=240), nullable=False),
        sa.Column("status", visit_status, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at", name="ck_visits_window"),
        sa.ForeignKeyConstraint(
            ["host_person_id"],
            ["people.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", name="uq_visits_seed_key"),
    )
    op.create_index("ix_visits_person_id", "visits", ["person_id"])
    op.create_index("ix_visits_site_id", "visits", ["site_id"])
    op.create_index("ix_visits_status", "visits", ["status"])
    op.create_index("ix_visits_window", "visits", ["starts_at", "ends_at"])

    op.create_table(
        "user_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", role, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("handle", name="uq_user_accounts_handle"),
    )
    op.create_index("ix_user_accounts_role", "user_accounts", ["role"])
    op.create_index("ix_user_accounts_person_id", "user_accounts", ["person_id"])

    op.create_table(
        "demo_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("baseline", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", name="uq_demo_scenarios_seed_key"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id"],
    )
    op.create_index(
        "ix_audit_events_occurred_at",
        "audit_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    """Remove the Batch 1 schema while retaining the Batch 0 foundation."""

    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("demo_scenarios")
    op.drop_index("ix_user_accounts_person_id", table_name="user_accounts")
    op.drop_index("ix_user_accounts_role", table_name="user_accounts")
    op.drop_table("user_accounts")
    op.drop_index("ix_visits_window", table_name="visits")
    op.drop_index("ix_visits_status", table_name="visits")
    op.drop_index("ix_visits_site_id", table_name="visits")
    op.drop_index("ix_visits_person_id", table_name="visits")
    op.drop_table("visits")
    op.drop_index("ix_people_standing", table_name="people")
    op.drop_index("ix_people_population", table_name="people")
    op.drop_index("ix_people_company_id", table_name="people")
    op.drop_table("people")
    op.drop_table("companies")
    op.drop_table("sites")
