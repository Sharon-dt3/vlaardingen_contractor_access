"""Versioned life-saving rules and each person's recorded confirmation of them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


# PUBLIC_INTERFACE
class LifeSavingRulesVersion(Base):
    """One published version of the life-saving rules, with its translations.

    ``content`` maps a language code to ``title``, ``intro``, ``rules`` (a list of
    ``{"title", "text"}`` items) and ``statement``: the exact sentence a person
    confirms. At most one version is current. Publishing a new version leaves
    earlier versions, and the confirmations recorded against them, untouched.
    """

    __tablename__ = "life_saving_rules_versions"
    __table_args__ = (
        UniqueConstraint("version", name="uq_life_saving_rules_versions_version"),
        Index(
            "uq_life_saving_rules_one_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# PUBLIC_INTERFACE
class LifeSavingRulesAcknowledgement(Base):
    """A person's own confirmation that they read and understood one rules version.

    The sentence they confirmed and a hash of the rules they were shown are stored
    with the record, so the evidence stays meaningful after the rules change.
    Rows are never updated: a new version needs a new confirmation.
    """

    __tablename__ = "life_saving_rules_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "rules_version_id",
            name="uq_life_saving_rules_acknowledgements_person_version",
        ),
        Index("ix_life_saving_rules_acknowledgements_person_id", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rules_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("life_saving_rules_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invitations.id", ondelete="SET NULL"),
        nullable=True,
    )
