"""Identity document uploaded by a walk-up person.

Adds the document's storage details and the ID expiry date the person typed, to both the
pending registration (before the email code is entered) and the registration itself.

Revision ID: 20261013_0022
Revises: 20261012_0021
"""

from alembic import op
import sqlalchemy as sa

revision = "20261013_0022"
down_revision = "20261012_0021"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("id_filename", sa.String(180)),
    ("id_media_type", sa.String(100)),
    ("id_size_bytes", sa.Integer()),
    ("id_sha256", sa.String(64)),
    ("id_storage_reference", sa.String(160)),
    ("id_storage_mode", sa.String(16)),
    ("id_expiry_date", sa.Date()),
)


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Add the document columns to both tables."""

    for table in ("walk_up_pending", "walk_up_registrations"):
        for name, kind in _COLUMNS:
            op.add_column(table, sa.Column(name, kind, nullable=True))


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove them again."""

    for table in ("walk_up_registrations", "walk_up_pending"):
        for name, _kind in reversed(_COLUMNS):
            op.drop_column(table, name)
