"""Persisted Batch 5 presence-event models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


# PUBLIC_INTERFACE
class PresenceEventType(str, enum.Enum):
    """The operational direction of an immutable site-presence event."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"


# PUBLIC_INTERFACE
class PresenceEvent(Base):
    """An immutable record of a confirmed site entry or recorded site exit."""

    __tablename__ = "presence_events"
    __table_args__ = (
        CheckConstraint(
            "(event_type = 'EXIT') OR gate_event_id IS NOT NULL",
            name="ck_presence_events_entry_has_gate_event",
        ),
        UniqueConstraint("gate_event_id", name="uq_presence_events_gate_event_id"),
        Index("ix_presence_events_visit_id", "visit_id"),
        Index("ix_presence_events_person_id", "person_id"),
        Index("ix_presence_events_site_id", "site_id"),
        Index("ix_presence_events_recorded_by_id", "recorded_by_id"),
        Index("ix_presence_events_occurred_at", "occurred_at"),
        Index("ix_presence_events_visit_occurred_at", "visit_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False,
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    gate_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gate_events.id", ondelete="RESTRICT"),
        nullable=True,
    )
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[PresenceEventType] = mapped_column(
        Enum(
            PresenceEventType,
            name="presence_event_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
