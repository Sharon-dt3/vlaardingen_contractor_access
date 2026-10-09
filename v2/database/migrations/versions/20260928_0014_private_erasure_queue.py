"""Persist recoverable private-object erasure work.

Revision ID: 20260928_0014
Revises: 20260928_0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260928_0014"
down_revision = "20260928_0013"
branch_labels = None
depends_on = None


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Create the person-scoped private erasure queue."""

    op.create_table(
        "private_erasure_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_reference", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "person_id", "storage_reference",
            name="uq_private_erasure_jobs_person_reference",
        ),
    )
    op.create_index(
        "ix_private_erasure_jobs_person_status",
        "private_erasure_jobs",
        ["person_id", "status"],
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove the queue only on an explicit migration rollback."""

    op.drop_index(
        "ix_private_erasure_jobs_person_status",
        table_name="private_erasure_jobs",
    )
    op.drop_table("private_erasure_jobs")
