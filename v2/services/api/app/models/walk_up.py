"""A person's arrival through the fixed QR code at a site entrance."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


# PUBLIC_INTERFACE
class WalkUpRegistration(Base):
    """One arrival: someone scanned the site's QR code, registered and confirmed the rules.

    There is no invitation behind it. The row ties the person to the site and to the
    life-saving confirmation they made at the same moment, so the site can see who
    arrived and that they confirmed before entering. A person who arrives again gets
    a new row, and reuses their earlier confirmation if the rules have not changed.
    """

    __tablename__ = "walk_up_registrations"
    __table_args__ = (
        Index("ix_walk_up_registrations_site_registered", "site_id", "registered_at"),
        Index("ix_walk_up_registrations_person_id", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="RESTRICT"), nullable=False
    )
    acknowledgement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("life_saving_rules_acknowledgements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="qr")
    # The pass is the QR the person shows at the kiosk. Only its hash is stored.
    pass_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    pass_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when a gate operator lets the person in, and by whom.
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    admitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    # Set when the person proved they own the email address (the code step).
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set when the person leaves, so the site knows who is still on site.
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )


# PUBLIC_INTERFACE
class WalkUpPending(Base):
    """A registration waiting for its email code. It is not a person yet.

    Nothing about the arrival is stored as a person or a confirmation until the code is
    entered, so nobody can create a confirmation under someone else's email address.
    """

    __tablename__ = "walk_up_pending"
    __table_args__ = (Index("ix_walk_up_pending_email_created", "email", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    company_name: Mapped[str] = mapped_column(String(180), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    population: Mapped[str] = mapped_column(String(32), nullable=False)
    rules_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("life_saving_rules_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sends: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
