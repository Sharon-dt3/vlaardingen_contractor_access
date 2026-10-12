"""Batch 1 relational domain, authentication, scenario, and audit models."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
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


class Population(str, enum.Enum):
    """Supported source populations for people entering a site."""

    RENEWI_DRIVER = "renewi_driver"
    TEMPORARY_DRIVER = "temporary_driver"
    EXTERNAL_DRIVER = "external_driver"
    MAINTENANCE_CONTRACTOR = "maintenance_contractor"
    PERMANENT_CONTRACTOR = "permanent_contractor"
    VISITOR = "visitor"


class PersonStanding(str, enum.Enum):
    """Current person-level standing, separate from visit workflow state."""

    ACTIVE = "active"
    BLOCKED = "blocked"
    INACTIVE = "inactive"


class VisitStatus(str, enum.Enum):
    """Foundational visit states used before later workflow batches."""

    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Role(str, enum.Enum):
    """Seeded API roles enforced by authorization dependencies."""

    SYSTEM_ADMIN = "system_admin"
    COMPLIANCE = "compliance"
    SITE_MANAGER = "site_manager"
    GATE_OPERATOR = "gate_operator"
    HOST = "host"
    PARTICIPANT = "participant"
    VIEWER = "viewer"


class Site(Base):
    """A physical site with local timezone and gate-mode configuration."""

    __tablename__ = "sites"
    __table_args__ = (
        CheckConstraint("country_code IN ('NL', 'BE')", name="ck_sites_country"),
        UniqueConstraint("seed_key", name="uq_sites_seed_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    gate_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Company(Base):
    """A fictional organization associated with people and visits."""

    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("seed_key", name="uq_companies_seed_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    company_type: Mapped[str] = mapped_column(String(48), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Person(Base):
    """A synthetic person whose standing is independent of visit state."""

    __tablename__ = "people"
    __table_args__ = (
        UniqueConstraint("seed_key", name="uq_people_seed_key"),
        Index("ix_people_company_id", "company_id"),
        Index("ix_people_population", "population"),
        Index("ix_people_standing", "standing"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    population: Mapped[Population] = mapped_column(
        Enum(
            Population,
            name="population",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    standing: Mapped[PersonStanding] = mapped_column(
        Enum(
            PersonStanding,
            name="person_standing",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=PersonStanding.ACTIVE,
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class Visit(Base):
    """A site visit retaining workflow state independently from a person."""

    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("seed_key", name="uq_visits_seed_key"),
        CheckConstraint("ends_at > starts_at", name="ck_visits_window"),
        Index("ix_visits_person_id", "person_id"),
        Index("ix_visits_site_id", "site_id"),
        Index("ix_visits_status", "status"),
        Index("ix_visits_window", "starts_at", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
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
    host_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )
    purpose: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[VisitStatus] = mapped_column(
        Enum(
            VisitStatus,
            name="visit_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserAccount(Base):
    """A local demo account with one authoritative API role."""

    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("handle", name="uq_user_accounts_handle"),
        Index("ix_user_accounts_role", "role"),
        Index("ix_user_accounts_person_id", "person_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    handle: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Staff accounts created from the Users screen. The demo account has none of these set.
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )


class DemoScenario(Base):
    """A deterministic scenario manifest used by later reset commands."""

    __tablename__ = "demo_scenarios"
    __table_args__ = (UniqueConstraint("seed_key", name="uq_demo_scenarios_seed_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    baseline: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditEvent(Base):
    """An immutable business-event record appended by domain commands."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


# PUBLIC_INTERFACE
class InvitationStatus(str, enum.Enum):
    """Workflow states owned by the invitation and registration lifecycle."""

    INVITED = "invited"
    PRE_REGISTERED = "pre_registered"
    EVIDENCE_READY = "evidence_ready"


# PUBLIC_INTERFACE
class EvidenceType(str, enum.Enum):
    """Synthetic document categories supported by the Batch 2 workflow."""

    ID_CARD = "id_card"
    DRIVING_LICENCE = "driving_licence"
    VCA_CERTIFICATE = "vca_certificate"
    INSURANCE_CERTIFICATE = "insurance_certificate"


# PUBLIC_INTERFACE
class EvidenceStatus(str, enum.Enum):
    """Review states for immutable or superseding evidence records."""

    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    VERIFIED = "verified"
    REJECTED = "rejected"
    REUPLOAD_REQUESTED = "reupload_requested"
    SUPERSEDED = "superseded"


# PUBLIC_INTERFACE
class Invitation(Base):
    """An invitation that links workflow state to eventual domain records."""

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("seed_key", name="uq_invitations_seed_key"),
        CheckConstraint("ends_at > starts_at", name="ck_invitations_window"),
        Index("ix_invitations_site_id", "site_id"),
        Index("ix_invitations_requested_by_id", "requested_by_id"),
        Index("ix_invitations_person_id", "person_id"),
        Index("ix_invitations_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(64), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invitee_email: Mapped[str] = mapped_column(String(254), nullable=False)
    population: Mapped[Population] = mapped_column(
        Enum(
            Population,
            name="invitation_population",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    company_name: Mapped[str] = mapped_column(String(180), nullable=False)
    purpose: Mapped[str] = mapped_column(String(240), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(
            InvitationStatus,
            name="invitation_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=InvitationStatus.INVITED,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=True,
    )
    visit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visits.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    # The private document is retained outside the web application. Only its
    # digest is used during gate scans, and neither value is exposed in APIs.
    identity_document_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    identity_document_storage_reference: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    identity_document_media_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    identity_document_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Workflow status remains independent of the recipient's email response.
    response_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="local_only"
    )
    response_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    response_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Issued only on acceptance; the bearer secret itself is never persisted.
    registration_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    registration_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


# PUBLIC_INTERFACE
class EvidenceAsset(Base):
    """A visibly fictional private asset with deterministic extraction fields."""

    __tablename__ = "evidence_assets"
    __table_args__ = (
        UniqueConstraint("asset_key", name="uq_evidence_assets_asset_key"),
        Index("ix_evidence_assets_type", "evidence_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    asset_key: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(
            EvidenceType,
            name="evidence_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(180), nullable=False)
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    expected_fields: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# PUBLIC_INTERFACE
class Evidence(Base):
    """Private evidence metadata and editable extraction-review state."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "expiry_date IS NULL OR issue_date IS NULL OR expiry_date >= issue_date",
            name="ck_evidence_date_order",
        ),
        Index("ix_evidence_person_id", "person_id"),
        Index("ix_evidence_invitation_id", "invitation_id"),
        Index("ix_evidence_status", "status"),
        Index("ix_evidence_expiry_date", "expiry_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invitations.id", ondelete="SET NULL"),
        nullable=True,
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(
            EvidenceType,
            name="evidence_type",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
        ),
        nullable=False,
    )
    status: Mapped[EvidenceStatus] = mapped_column(
        Enum(
            EvidenceStatus,
            name="evidence_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
        default=EvidenceStatus.UPLOADED,
    )
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    storage_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    extracted_fields: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    field_confidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    validity_assessment: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence.id", ondelete="SET NULL"),
        nullable=True,
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
