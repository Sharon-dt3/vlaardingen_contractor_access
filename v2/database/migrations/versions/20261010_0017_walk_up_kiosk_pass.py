"""Walk-up arrivals get a pass the kiosk can scan, and a record of who let them in.

Revision ID: 20261010_0017
Revises: 20261010_0016
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_0017"
down_revision = "20261010_0016"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Add the pass hash and expiry, and the entry decision."""

    op.add_column("walk_up_registrations", sa.Column("pass_hash", sa.String(64), nullable=True))
    op.add_column(
        "walk_up_registrations", sa.Column("pass_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "walk_up_registrations", sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "walk_up_registrations",
        sa.Column(
            "admitted_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_walk_up_registrations_pass_hash", "walk_up_registrations", ["pass_hash"], unique=True
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove the pass and entry columns."""

    op.drop_index("uq_walk_up_registrations_pass_hash", table_name="walk_up_registrations")
    op.drop_column("walk_up_registrations", "admitted_by_id")
    op.drop_column("walk_up_registrations", "admitted_at")
    op.drop_column("walk_up_registrations", "pass_expires_at")
    op.drop_column("walk_up_registrations", "pass_hash")
