"""Pydantic contracts for Batch 2 invitation and evidence workflows."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import (
    EvidenceStatus,
    EvidenceType,
    InvitationStatus,
    Population,
)


# PUBLIC_INTERFACE
class InvitationCreate(BaseModel):
    """Validated invitation command."""

    site_id: uuid.UUID = Field(..., description="Target active site identifier.")
    invitee_email: EmailStr = Field(
        ...,
        description="Recipient address for invitation delivery; it does not identify a person.",
    )
    population: Population = Field(..., description="Source population.")
    company_name: str = Field(
        ...,
        min_length=2,
        max_length=180,
        description="Fictional company name proposed by the requester.",
    )
    purpose: str = Field(
        ...,
        min_length=3,
        max_length=240,
        description="Business purpose of the planned visit.",
    )
    starts_at: datetime = Field(..., description="Timezone-aware visit start.")
    ends_at: datetime = Field(..., description="Timezone-aware visit end.")

    @model_validator(mode="after")
    def validate_window(self) -> "InvitationCreate":
        """Ensure the invitation contains a valid timezone-aware visit window."""

        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Visit start and end must include timezone information.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Visit end must be later than visit start.")
        return self


# PUBLIC_INTERFACE
class InvitationResponse(BaseModel):
    """Invitation workflow state and linked-record identifiers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seed_key: str
    site_id: uuid.UUID
    requested_by_id: uuid.UUID
    invitee_email: str
    population: Population
    company_name: str
    purpose: str
    starts_at: datetime
    ends_at: datetime
    status: InvitationStatus
    company_id: uuid.UUID | None
    person_id: uuid.UUID | None
    registered_name: str | None = Field(
        default=None,
        description="Name of the person linked to this authorized invitation, if registered.",
    )
    visit_id: uuid.UUID | None
    identity_document_uploaded_at: datetime | None
    response_status: str = Field(
        ..., description="Recipient choice: pending, accepted, or declined."
    )
    responded_at: datetime | None = Field(
        ..., description="Timestamp of the recorded recipient choice."
    )
    registration_completed_at: datetime | None = Field(
        ..., description="When the recipient supplied registration details and required evidence."
    )
    delivery_status: str = Field(
        ..., description="SMTP sent, SMTP failed, or local-only; not inbox receipt."
    )
    created_at: datetime
    updated_at: datetime


# PUBLIC_INTERFACE
class InviteeRegistrationCreate(BaseModel):
    """Recipient-supplied identity details; email and company come from the invitation."""

    first_name: str = Field(
        ..., min_length=1, max_length=100,
        description="Invitee's first name as it appears on the identity document.",
    )
    last_name: str = Field(
        ..., min_length=1, max_length=120,
        description="Invitee's last name as it appears on the identity document.",
    )
    expiry_date: date = Field(
        ...,
        description="Expiry date printed on the submitted ID; supplied by the invitee and not yet verified.",
    )

    @model_validator(mode="after")
    def validate_names(self) -> "InviteeRegistrationCreate":
        """Disallow whitespace-only names and already-expired IDs."""

        if not self.first_name.strip() or not self.last_name.strip():
            raise ValueError("First and last names are required.")
        if self.expiry_date < date.today():
            raise ValueError("The identity document must not already be expired.")
        return self


# PUBLIC_INTERFACE
class InviteeRegistrationStatus(BaseModel):
    """Minimal invitation state available to the holder of its registration link."""

    company_name: str = Field(..., description="Inviting company.")
    population: Population = Field(..., description="Determines the required identity document.")
    registration_completed: bool = Field(..., description="Whether the recipient finished submission.")
    evidence_uploaded: bool = Field(..., description="Whether required identity evidence was submitted.")
    life_saving_rules_confirmed: bool = Field(
        default=False,
        description="Whether the recipient confirmed the life-saving rules now in force.",
    )
    life_saving_rules_confirmed_at: datetime | None = Field(
        default=None,
        description="When the recipient confirmed the rules now in force.",
    )


# PUBLIC_INTERFACE
class RegistrationCreate(BaseModel):
    """Create-or-link registration command for an invited participant."""

    company_id: uuid.UUID | None = Field(
        default=None,
        description="Existing fictional company to link when known.",
    )
    company_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=180,
        description="Company name used when creating or duplicate-matching.",
    )
    company_type: str = Field(
        default="contractor",
        min_length=2,
        max_length=48,
        description="Type assigned to a newly created fictional company.",
    )
    company_country_code: str = Field(
        default="NL",
        pattern="^(NL|BE)$",
        description="Supported fictional company country.",
    )
    person_id: uuid.UUID | None = Field(
        default=None,
        description="Existing synthetic person to link when known.",
    )
    first_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="First name required when creating a person.",
    )
    last_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="Last name required when creating a person.",
    )
    email: EmailStr | None = Field(
        default=None,
        description="Contact email; automatic person reuse also requires matching name and company.",
    )

    @model_validator(mode="after")
    def validate_create_or_link_fields(self) -> "RegistrationCreate":
        """Require names only when no existing person identifier is supplied."""

        if self.person_id is None and (not self.first_name or not self.last_name):
            raise ValueError(
                "first_name and last_name are required when creating a person."
            )
        return self


# PUBLIC_INTERFACE
class RegistrationResponse(BaseModel):
    """Linked registration result and resulting invitation workflow state."""

    invitation: InvitationResponse
    company_id: uuid.UUID
    person_id: uuid.UUID
    visit_id: uuid.UUID
    company_created: bool
    person_created: bool


# PUBLIC_INTERFACE
class EvidenceAssetResponse(BaseModel):
    """Safe catalog metadata for a private synthetic evidence asset."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_key: str
    evidence_type: EvidenceType
    display_name: str
    filename: str
    media_type: str
    size_bytes: int
    expected_fields: dict[str, Any]
    issue_date: date | None
    expiry_date: date | None
    is_active: bool


# PUBLIC_INTERFACE
class SyntheticEvidenceAttach(BaseModel):
    """Attach a seeded private synthetic asset to a registered invitation."""

    asset_id: uuid.UUID = Field(..., description="Active synthetic asset identifier.")


# PUBLIC_INTERFACE
class EvidenceFieldsUpdate(BaseModel):
    """Reviewer corrections for extracted evidence fields and validity dates."""

    fields: dict[str, Any] = Field(
        ...,
        description="Complete edited field set replacing the extraction result.",
    )
    issue_date: date | None = Field(
        default=None,
        description="Reviewed document issue date.",
    )
    expiry_date: date | None = Field(
        default=None,
        description="Reviewed document expiry date.",
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "EvidenceFieldsUpdate":
        """Reject an expiry date that precedes the issue date."""

        if (
            self.issue_date is not None
            and self.expiry_date is not None
            and self.expiry_date < self.issue_date
        ):
            raise ValueError("expiry_date must not precede issue_date.")
        return self


# PUBLIC_INTERFACE
class EvidenceReviewCommand(BaseModel):
    """Human-readable reviewer reason for a material evidence decision."""

    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Reason recorded in evidence state and append-only audit history.",
    )


# PUBLIC_INTERFACE
class GateEvidenceExtractionRequest(BaseModel):
    """Opaque token input authorizing extraction of its matching gate upload."""

    token_reference: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Scanned opaque token used for server-side evidence association.",
    )


# PUBLIC_INTERFACE
class GateIdentityScanResponse(BaseModel):
    """Authoritative result of matching a gate-scanned ID to its invitation."""

    matched: bool = Field(
        ...,
        description="Whether the scanned private ID exactly matches the invitation ID.",
    )
    reason_code: str = Field(
        ...,
        description="Stable server-generated result code for the ID match.",
    )
    detail: str = Field(
        ...,
        description="Operator-safe explanation that contains no identity-document data.",
    )


# PUBLIC_INTERFACE
class EvidenceResponse(BaseModel):
    """Authorized evidence metadata without a private storage path."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    invitation_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    evidence_type: EvidenceType
    status: EvidenceStatus
    filename: str
    media_type: str
    size_bytes: int
    content_sha256: str
    storage_mode: str
    provider_mode: str
    extracted_fields: dict[str, Any]
    field_confidence: dict[str, Any]
    validity_assessment: dict[str, Any]
    issue_date: date | None
    expiry_date: date | None
    review_notes: str | None
    supersedes_id: uuid.UUID | None
    uploaded_by_id: uuid.UUID
    reviewed_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
