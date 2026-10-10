"""Add walk-up registrations: arrival through the fixed QR code, with no invitation.

Revision ID: 20261010_0016
Revises: 20261009_0015
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_0016"
down_revision = "20261009_0015"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Create the table that records each QR arrival."""

    op.create_table(
        "walk_up_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "acknowledgement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("life_saving_rules_acknowledgements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default="qr"),
    )
    op.create_index(
        "ix_walk_up_registrations_site_registered",
        "walk_up_registrations",
        ["site_id", "registered_at"],
    )
    op.create_index(
        "ix_walk_up_registrations_person_id", "walk_up_registrations", ["person_id"]
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Drop the QR arrival table."""

    op.drop_index("ix_walk_up_registrations_person_id", table_name="walk_up_registrations")
    op.drop_index(
        "ix_walk_up_registrations_site_registered", table_name="walk_up_registrations"
    )
    op.drop_table("walk_up_registrations")
