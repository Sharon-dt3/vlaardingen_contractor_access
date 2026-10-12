"""Staff accounts: email, lockout counters and single-use links.

Adds the fields a staff account needs to be invited by email and to sign in safely, and
the table that holds hashed, single-use, expiring invitation and reset links.

Revision ID: 20261013_0023
Revises: 20261013_0022
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261013_0023"
down_revision = "20261013_0022"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Extend user_accounts and add account_tokens."""

    op.add_column("user_accounts", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("user_accounts", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "user_accounts",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("user_accounts", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_accounts", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "user_accounts",
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_user_accounts_email",
        "user_accounts",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_table(
        "account_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("kind IN ('invite', 'reset')", name="ck_account_tokens_kind"),
    )
    op.create_index("ix_account_tokens_account_id", "account_tokens", ["account_id"])


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove them again."""

    op.drop_index("ix_account_tokens_account_id", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_index("uq_user_accounts_email", table_name="user_accounts")
    for name in ("created_by_id", "password_changed_at", "locked_until", "failed_attempts", "last_login_at", "email"):
        op.drop_column("user_accounts", name)
