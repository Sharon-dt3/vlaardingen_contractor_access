"""Add accepted-invitee registration capability and completion state.

Revision ID: 20260928_0012
Revises: 20260925_0011
"""

from alembic import op
import sqlalchemy as sa

revision = "20260928_0012"
down_revision = "20260925_0011"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Add recipient registration state without changing existing records."""

    op.add_column(
        "invitations",
        sa.Column("registration_token_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "invitations",
        sa.Column(
            "registration_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "invitations",
        sa.Column(
            "registration_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_invitations_registration_token_hash",
        "invitations",
        ["registration_token_hash"],
        unique=True,
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove recipient registration state if rolling back this revision."""

    op.drop_index(
        "ix_invitations_registration_token_hash",
        table_name="invitations",
    )
    op.drop_column("invitations", "registration_completed_at")
    op.drop_column("invitations", "registration_token_expires_at")
    op.drop_column("invitations", "registration_token_hash")
