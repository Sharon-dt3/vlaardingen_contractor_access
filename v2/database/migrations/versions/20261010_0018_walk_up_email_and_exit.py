"""Walk-up email check and exit recording.

Adds a short-lived pending registration (the email code step), a verified-at time on a
registration, and the exit time and operator so the site can see who is on site.

Revision ID: 20261010_0018
Revises: 20261010_0017
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261010_0018"
down_revision = "20261010_0017"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Create the pending table and add the verification and exit columns."""

    op.add_column(
        "walk_up_registrations", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "walk_up_registrations", sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "walk_up_registrations",
        sa.Column(
            "exited_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_table(
        "walk_up_pending",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("company_name", sa.String(180), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("population", sa.String(32), nullable=False),
        sa.Column(
            "rules_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("life_saving_rules_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sends", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_walk_up_pending_email_created", "walk_up_pending", ["email", "created_at"])


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove the pending table and the added columns."""

    op.drop_index("ix_walk_up_pending_email_created", table_name="walk_up_pending")
    op.drop_table("walk_up_pending")
    op.drop_column("walk_up_registrations", "exited_by_id")
    op.drop_column("walk_up_registrations", "exited_at")
    op.drop_column("walk_up_registrations", "email_verified_at")
