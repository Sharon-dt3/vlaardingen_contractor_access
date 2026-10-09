"""Persisted Batch 6 demo-time, expiry-alert, and re-validation models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


# PUBLIC_INTERFACE
class ExpirySubjectKind(str, enum.Enum):
    """The evidence or training source monitored for renewal."""

    EVIDENCE = "EVIDENCE"
    TRAINING = "TRAINING"


# PUBLIC_INTERFACE
class RevalidationTaskStatus(str, enum.Enum):
    """The lifecycle state of an expiry-triggered re-validation task."""

    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


# PUBLIC_INTERFACE
class DemoClock(Base):
    """The singleton persisted effective clock used by deterministic demo workflows."""

    __tablename__ = "demo_clock"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_demo_clock_singleton_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )


# PUBLIC_INTERFACE
class ExpiryAlert(Base):
    """A durable in-app expiry alert with idempotent notification delivery metadata."""

    __tablename__ = "expiry_alerts"
    __table_args__ = (
        UniqueConstraint(
            "source_kind",
            "source_id",
            "alert_code",
            name="uq_expiry_alerts_source_code",
        ),
        Index("ix_expiry_alerts_person_id", "person_id"),
        Index("ix_expiry_alerts_requirement_id", "requirement_id"),
        Index("ix_expiry_alerts_site_id", "site_id"),
        Index("ix_expiry_alerts_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("compliance_requirements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_kind: Mapped[ExpirySubjectKind] = mapped_column(
        Enum(
            ExpirySubjectKind,
            name="expiry_subject_kind",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    alert_code: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    delivery_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )


# PUBLIC_INTERFACE
class RevalidationTask(Base):
    """A unique actionable task requiring renewal after a monitored source expires."""

    __tablename__ = "revalidation_tasks"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "requirement_id",
            "source_kind",
            "source_id",
            name="uq_revalidation_tasks_source",
        ),
        Index("ix_revalidation_tasks_person_id", "person_id"),
        Index("ix_revalidation_tasks_site_id", "site_id"),
        Index("ix_revalidation_tasks_status", "status"),
        Index("ix_revalidation_tasks_requirement_id", "requirement_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("compliance_requirements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_kind: Mapped[ExpirySubjectKind] = mapped_column(
        Enum(
            ExpirySubjectKind,
            name="expiry_subject_kind",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
        ),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[RevalidationTaskStatus] = mapped_column(
        Enum(
            RevalidationTaskStatus,
            name="revalidation_task_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=RevalidationTaskStatus.OPEN,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
