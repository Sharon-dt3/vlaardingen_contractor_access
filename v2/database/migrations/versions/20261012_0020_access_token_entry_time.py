"""Entry time on an access token.

An access token already stops working at ``expires_at``. This adds the time it starts
working, so staff can set both when they issue it.

Revision ID: 20261012_0020
Revises: 20261011_0019
"""

from alembic import op
import sqlalchemy as sa

revision = "20261012_0020"
down_revision = "20261011_0019"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Add the optional entry time."""

    op.add_column("access_tokens", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove the entry time."""

    op.drop_column("access_tokens", "valid_from")
