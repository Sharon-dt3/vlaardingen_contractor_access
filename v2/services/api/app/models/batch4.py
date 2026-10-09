"""Persisted Batch 4 identity-verification and gate-decision models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


# PUBLIC_INTERFACE
class GateDecision(str, enum.Enum):
    """The final, backend-authoritative outcome of a gate evaluation."""

    GRANT = "GRANT"
    DENY = "DENY"


# PUBLIC_INTERFACE
class GateEvent(Base):
    """An immutable token scan and authoritative gate-decision snapshot."""

    __tablename__ = "gate_events"
    __table_args__ = (
        Index("ix_gate_events_token_id", "token_id"),
        Index("ix_gate_events_visit_id", "visit_id"),
        Index("ix_gate_events_person_id", "person_id"),
        Index("ix_gate_events_operator_id", "operator_id"),
        Index("ix_gate_events_decision", "decision"),
        Index("ix_gate_events_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("access_tokens.id", ondelete="RESTRICT"),
        nullable=True,
    )
    requested_site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=True,
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scanned_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[GateDecision] = mapped_column(
        Enum(
            GateDecision,
            name="gate_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    corrective_actions: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    identity_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


# PUBLIC_INTERFACE
class IdentityVerification(Base):
    """A persisted deterministic provider result associated with one gate event."""

    __tablename__ = "identity_verifications"
    __table_args__ = (
        Index("ix_identity_verifications_person_id", "person_id"),
        Index("ix_identity_verifications_evaluated_at", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gate_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gate_events.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False,
    )
    presentation_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    is_match: Mapped[bool] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
