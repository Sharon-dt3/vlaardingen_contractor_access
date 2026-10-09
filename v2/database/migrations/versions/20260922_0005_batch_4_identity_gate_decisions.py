"""Create Batch 4 identity verification and gate decision persistence.

Revision ID: 20260922_0005
Revises: 20260922_0004
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0005"
down_revision: str | None = "20260922_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

gate_decision = sa.Enum(
    "GRANT",
    "DENY",
    name="gate_decision",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Create immutable gate-event and identity-verification snapshot tables."""

    op.create_table(
        "gate_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "requested_site_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scanned_reference_hash", sa.String(length=64), nullable=False),
        sa.Column("decision", gate_decision, nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("corrective_actions", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("identity_snapshot", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_site_id"],
            ["sites.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["access_tokens.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gate_events_token_id", "gate_events", ["token_id"])
    op.create_index("ix_gate_events_visit_id", "gate_events", ["visit_id"])
    op.create_index("ix_gate_events_person_id", "gate_events", ["person_id"])
    op.create_index("ix_gate_events_operator_id", "gate_events", ["operator_id"])
    op.create_index("ix_gate_events_decision", "gate_events", ["decision"])
    op.create_index(
        "ix_gate_events_occurred_at",
        "gate_events",
        ["occurred_at"],
    )

    op.create_table(
        "identity_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "gate_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "presentation_reference",
            sa.String(length=160),
            nullable=False,
        ),
        sa.Column("is_match", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provider_mode", sa.String(length=16), nullable=False),
        sa.Column(
            "provider_reference",
            sa.String(length=160),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["gate_event_id"],
            ["gate_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gate_event_id"),
    )
    op.create_index(
        "ix_identity_verifications_person_id",
        "identity_verifications",
        ["person_id"],
    )
    op.create_index(
        "ix_identity_verifications_evaluated_at",
        "identity_verifications",
        ["evaluated_at"],
    )


def downgrade() -> None:
    """Remove Batch 4 persistence while retaining Batch 3 data."""

    op.drop_index(
        "ix_identity_verifications_evaluated_at",
        table_name="identity_verifications",
    )
    op.drop_index(
        "ix_identity_verifications_person_id",
        table_name="identity_verifications",
    )
    op.drop_table("identity_verifications")
    op.drop_index("ix_gate_events_occurred_at", table_name="gate_events")
    op.drop_index("ix_gate_events_decision", table_name="gate_events")
    op.drop_index("ix_gate_events_operator_id", table_name="gate_events")
    op.drop_index("ix_gate_events_person_id", table_name="gate_events")
    op.drop_index("ix_gate_events_visit_id", table_name="gate_events")
    op.drop_index("ix_gate_events_token_id", table_name="gate_events")
    op.drop_table("gate_events")
