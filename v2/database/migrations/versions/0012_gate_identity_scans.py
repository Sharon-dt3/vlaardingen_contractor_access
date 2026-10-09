"""Store single-use, token-bound gate identity scans.

Revision ID: 20260925_0011
Revises: 20260925_0010
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260925_0011"
down_revision = "20260925_0010"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Create the private gate scan result table."""
    op.create_table(
        "gate_identity_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invitation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invitations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "operator_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("token_reference_hash", sa.String(64), nullable=False),
        sa.Column("invitation_identity_sha256", sa.String(64), nullable=True),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_gate_identity_scans_operator_token",
        "gate_identity_scans",
        ["operator_id", "token_reference_hash"],
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove the private gate scan result table."""
    op.drop_index(
        "ix_gate_identity_scans_operator_token", table_name="gate_identity_scans"
    )
    op.drop_table("gate_identity_scans")
