"""Add life-saving rules versions and personal confirmations.

A contractor must confirm that they have read and understood the life-saving
rules before entering site, and the site must be able to see that they did.
This revision stores each published version of the rules, stores each person's
own confirmation of a version, and allows a compliance requirement to be of the
new ``LIFE_SAVING_RULES`` kind so the approval and gate checks can require it.

Revision ID: 20261009_0015
Revises: 20260928_0014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261009_0015"
down_revision = "20260928_0014"
branch_labels = None
depends_on = None

_OLD_SUBJECT_CHECK = (
    "(requirement_kind = 'EVIDENCE' AND evidence_type IS NOT NULL "
    "AND training_module_id IS NULL) OR "
    "(requirement_kind = 'TRAINING' AND training_module_id IS NOT NULL "
    "AND evidence_type IS NULL)"
)
_NEW_SUBJECT_CHECK = (
    _OLD_SUBJECT_CHECK
    + " OR (requirement_kind = 'LIFE_SAVING_RULES' AND evidence_type IS NULL "
    "AND training_module_id IS NULL)"
)


# PUBLIC_INTERFACE
def upgrade() -> None:
    """Create the rules and confirmation tables and widen the requirement kinds."""

    op.create_table(
        "life_saving_rules_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version", name="uq_life_saving_rules_versions_version"),
    )
    op.create_index(
        "uq_life_saving_rules_one_current",
        "life_saving_rules_versions",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "life_saving_rules_acknowledgements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rules_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("statement_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(40), nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["rules_version_id"],
            ["life_saving_rules_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["invitations.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "person_id",
            "rules_version_id",
            name="uq_life_saving_rules_acknowledgements_person_version",
        ),
    )
    op.create_index(
        "ix_life_saving_rules_acknowledgements_person_id",
        "life_saving_rules_acknowledgements",
        ["person_id"],
    )

    # The requirement kind column was sized for the two original kinds (8 characters).
    op.drop_constraint(
        "compliance_requirement_kind", "compliance_requirements", type_="check"
    )
    op.drop_constraint(
        "ck_compliance_requirement_subject", "compliance_requirements", type_="check"
    )
    op.alter_column(
        "compliance_requirements",
        "requirement_kind",
        existing_type=sa.String(8),
        type_=sa.String(32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "compliance_requirement_kind",
        "compliance_requirements",
        "requirement_kind IN ('EVIDENCE', 'TRAINING', 'LIFE_SAVING_RULES')",
    )
    op.create_check_constraint(
        "ck_compliance_requirement_subject",
        "compliance_requirements",
        _NEW_SUBJECT_CHECK,
    )


# PUBLIC_INTERFACE
def downgrade() -> None:
    """Remove the confirmations and return requirements to evidence and training only."""

    op.drop_index(
        "ix_life_saving_rules_acknowledgements_person_id",
        table_name="life_saving_rules_acknowledgements",
    )
    op.drop_table("life_saving_rules_acknowledgements")
    op.drop_index(
        "uq_life_saving_rules_one_current", table_name="life_saving_rules_versions"
    )
    op.drop_table("life_saving_rules_versions")

    op.execute(
        "DELETE FROM compliance_requirements WHERE requirement_kind = 'LIFE_SAVING_RULES'"
    )
    op.drop_constraint(
        "ck_compliance_requirement_subject", "compliance_requirements", type_="check"
    )
    op.drop_constraint(
        "compliance_requirement_kind", "compliance_requirements", type_="check"
    )
    op.alter_column(
        "compliance_requirements",
        "requirement_kind",
        existing_type=sa.String(32),
        type_=sa.String(8),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "compliance_requirement_kind",
        "compliance_requirements",
        "requirement_kind IN ('EVIDENCE', 'TRAINING')",
    )
    op.create_check_constraint(
        "ck_compliance_requirement_subject",
        "compliance_requirements",
        _OLD_SUBJECT_CHECK,
    )
