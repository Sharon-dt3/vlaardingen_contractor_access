"""Per-site access validity settings.

Lets an administrator set the default visit length (Path A) and the walk-up entry QR
validity (Path B) for each site, instead of a number fixed in the code.

Revision ID: 20261011_0019
Revises: 20261010_0018
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261011_0019"
down_revision = "20261010_0018"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Create the settings table."""

    op.create_table(
        "site_access_settings",
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("visit_default_hours", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("walk_up_pass_hours", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("visit_default_hours BETWEEN 1 AND 168", name="ck_site_settings_visit"),
        sa.CheckConstraint("walk_up_pass_hours BETWEEN 1 AND 72", name="ck_site_settings_pass"),
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Drop the settings table."""

    op.drop_table("site_access_settings")
