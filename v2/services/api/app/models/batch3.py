"""Persisted Batch 3 training, compliance, approval, and access-token models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.domain import EvidenceType, Population


# PUBLIC_INTERFACE
class TrainingOutcome(str, enum.Enum):
    """The calculated outcome of a scored training attempt."""

    PASSED = "passed"
    FAILED = "failed"


# PUBLIC_INTERFACE
class BlacklistSubjectType(str, enum.Enum):
    """The durable record type targeted by a blacklist entry."""

    PERSON = "person"
    COMPANY = "company"


# PUBLIC_INTERFACE
class ComplianceRequirementKind(str, enum.Enum):
    """The supported types of configurable compliance requirements."""

    EVIDENCE = "evidence"
    TRAINING = "training"
    LIFE_SAVING_RULES = "life_saving_rules"


# PUBLIC_INTERFACE
class ApprovalDecision(str, enum.Enum):
    """The lifecycle state of an auditable visit approval."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTION_REQUESTED = "correction_requested"
    SUPERSEDED = "superseded"


# PUBLIC_INTERFACE
class AccessTokenStatus(str, enum.Enum):
    """The server-side state of an opaque visit-bound access token."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# PUBLIC_INTERFACE
class TrainingModule(Base):
    """A scored, language-specific training module with synthetic questions."""

    __tablename__ = "training_modules"
    __table_args__ = (
        UniqueConstraint("code", name="uq_training_modules_code"),
        Index("ix_training_modules_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    passing_score: Mapped[int] = mapped_column(Integer, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# PUBLIC_INTERFACE
class TrainingResult(Base):
    """An immutable scored training attempt for a person and module."""

    __tablename__ = "training_results"
    __table_args__ = (
        CheckConstraint(
            "score >= 0 AND score <= 100",
            name="ck_training_results_score_range",
        ),
        UniqueConstraint(
            "person_id",
            "training_module_id",
            "attempt_number",
            name="uq_training_results_attempt",
        ),
        Index("ix_training_results_person_id", "person_id"),
        Index("ix_training_results_module_id", "training_module_id"),
        Index("ix_training_results_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False,
    )
    training_module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_modules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[TrainingOutcome] = mapped_column(
        Enum(
            TrainingOutcome,
            name="training_outcome",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    answers: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


# PUBLIC_INTERFACE
class BlacklistEntry(Base):
    """A reversible, auditable person- or company-level blacklist entry."""

    __tablename__ = "blacklist_entries"
    __table_args__ = (
        CheckConstraint(
            "(person_id IS NOT NULL AND company_id IS NULL) OR "
            "(person_id IS NULL AND company_id IS NOT NULL)",
            name="ck_blacklist_entries_single_subject",
        ),
        Index("ix_blacklist_entries_person_id", "person_id"),
        Index("ix_blacklist_entries_company_id", "company_id"),
        Index("ix_blacklist_entries_active_window", "is_active", "starts_at", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    subject_type: Mapped[BlacklistSubjectType] = mapped_column(
        Enum(
            BlacklistSubjectType,
            name="blacklist_subject_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=True,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


# PUBLIC_INTERFACE
class ComplianceRequirement(Base):
    """A configurable site and population compliance requirement."""

    __tablename__ = "compliance_requirements"
    __table_args__ = (
        CheckConstraint(
            "(requirement_kind = 'EVIDENCE' AND evidence_type IS NOT NULL "
            "AND training_module_id IS NULL) OR "
            "(requirement_kind = 'TRAINING' AND training_module_id IS NOT NULL "
            "AND evidence_type IS NULL) OR "
            "(requirement_kind = 'LIFE_SAVING_RULES' AND evidence_type IS NULL "
            "AND training_module_id IS NULL)",
            name="ck_compliance_requirement_subject",
        ),
        UniqueConstraint(
            "site_id",
            "population",
            "code",
            name="uq_compliance_requirements_site_population_code",
        ),
        Index("ix_compliance_requirements_site_id", "site_id"),
        Index("ix_compliance_requirements_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    population: Mapped[Population | None] = mapped_column(
        Enum(
            Population,
            name="compliance_population",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(180), nullable=False)
    requirement_kind: Mapped[ComplianceRequirementKind] = mapped_column(
        Enum(
            ComplianceRequirementKind,
            name="compliance_requirement_kind",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    evidence_type: Mapped[EvidenceType | None] = mapped_column(
        Enum(
            EvidenceType,
            name="evidence_type",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
        ),
        nullable=True,
    )
    training_module_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_modules.id", ondelete="RESTRICT"),
        nullable=True,
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# PUBLIC_INTERFACE
class Approval(Base):
    """An auditable eligibility evaluation and decision for one site visit."""

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_visit_id", "visit_id"),
        Index("ix_approvals_decision", "decision"),
        Index("ix_approvals_decided_at", "decided_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(
            ApprovalDecision,
            name="approval_decision",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=ApprovalDecision.PENDING,
    )
    compliance_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


# PUBLIC_INTERFACE
class AccessToken(Base):
    """A visit-bound opaque access-token record that stores only a hash."""

    __tablename__ = "access_tokens"
    __table_args__ = (
        UniqueConstraint("reference_hash", name="uq_access_tokens_reference_hash"),
        Index("ix_access_tokens_visit_id", "visit_id"),
        Index("ix_access_tokens_status", "status"),
        Index("ix_access_tokens_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AccessTokenStatus] = mapped_column(
        Enum(
            AccessTokenStatus,
            name="access_token_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=AccessTokenStatus.ACTIVE,
    )
    issued_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
