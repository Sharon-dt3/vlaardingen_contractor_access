"""Retire VCA access requirements without deleting historical evidence.

Revision ID: 20260928_0013
Revises: 20260928_0012
"""

from alembic import op
import sqlalchemy as sa

revision = "20260928_0013"
down_revision = "20260928_0012"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Deactivate VCA compliance rules while retaining linked history."""

    # Do not delete requirements: expiry alerts and revalidation tasks may
    # reference their IDs, and historic approvals retain their own snapshots.
    op.execute(
        sa.text(
            "UPDATE compliance_requirements "
            "SET is_active = false, is_required = false, is_blocking = false "
            "WHERE evidence_type = 'VCA_CERTIFICATE'"
        )
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Leave retired requirements inactive rather than restore a safety blocker."""

    # Historical configuration cannot distinguish formerly active rules from
    # rules intentionally inactive before this migration.
    pass
