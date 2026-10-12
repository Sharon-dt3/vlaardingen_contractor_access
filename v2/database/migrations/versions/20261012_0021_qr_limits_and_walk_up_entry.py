"""Longest access QR, and a configurable entry time for walk-up QR codes.

Revision ID: 20261012_0021
Revises: 20261012_0020
"""

from alembic import op
import sqlalchemy as sa

revision = "20261012_0021"
down_revision = "20261012_0020"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Add the two settings and the walk-up entry time."""

    op.add_column(
        "site_access_settings",
        sa.Column("access_qr_max_hours", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column(
        "site_access_settings",
        sa.Column("walk_up_entry_delay_minutes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_site_settings_qr_max", "site_access_settings", "access_qr_max_hours BETWEEN 1 AND 168"
    )
    op.create_check_constraint(
        "ck_site_settings_delay",
        "site_access_settings",
        "walk_up_entry_delay_minutes BETWEEN 0 AND 240",
    )
    op.add_column(
        "walk_up_registrations",
        sa.Column("pass_valid_from", sa.DateTime(timezone=True), nullable=True),
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove them again."""

    op.drop_column("walk_up_registrations", "pass_valid_from")
    op.drop_constraint("ck_site_settings_delay", "site_access_settings", type_="check")
    op.drop_constraint("ck_site_settings_qr_max", "site_access_settings", type_="check")
    op.drop_column("site_access_settings", "walk_up_entry_delay_minutes")
    op.drop_column("site_access_settings", "access_qr_max_hours")
