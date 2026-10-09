"""Create Batch 5 explicit presence-event persistence.

Revision ID: 20260922_0006
Revises: 20260922_0005
Create Date: 2026-09-22
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0006"
down_revision: str | None = "20260922_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

presence_event_type = sa.Enum(
    "ENTRY",
    "EXIT",
    name="presence_event_type",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    """Create immutable occupancy events used by presence projections."""

    op.create_table(
        "presence_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gate_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recorded_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("event_type", presence_event_type, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(event_type = 'EXIT') OR gate_event_id IS NOT NULL",
            name="ck_presence_events_entry_has_gate_event",
        ),
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
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["user_accounts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visit_id"],
            ["visits.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gate_event_id",
            name="uq_presence_events_gate_event_id",
        ),
    )
    op.create_index(
        "ix_presence_events_visit_id",
        "presence_events",
        ["visit_id"],
    )
    op.create_index(
        "ix_presence_events_person_id",
        "presence_events",
        ["person_id"],
    )
    op.create_index(
        "ix_presence_events_site_id",
        "presence_events",
        ["site_id"],
    )
    op.create_index(
        "ix_presence_events_recorded_by_id",
        "presence_events",
        ["recorded_by_id"],
    )
    op.create_index(
        "ix_presence_events_occurred_at",
        "presence_events",
        ["occurred_at"],
    )
    op.create_index(
        "ix_presence_events_visit_occurred_at",
        "presence_events",
        ["visit_id", "occurred_at"],
    )


def downgrade() -> None:
    """Remove Batch 5 occupancy-event persistence while retaining Batch 4 data."""

    op.drop_index(
        "ix_presence_events_visit_occurred_at",
        table_name="presence_events",
    )
    op.drop_index("ix_presence_events_occurred_at", table_name="presence_events")
    op.drop_index(
        "ix_presence_events_recorded_by_id",
        table_name="presence_events",
    )
    op.drop_index("ix_presence_events_site_id", table_name="presence_events")
    op.drop_index("ix_presence_events_person_id", table_name="presence_events")
    op.drop_index("ix_presence_events_visit_id", table_name="presence_events")
    op.drop_table("presence_events")
