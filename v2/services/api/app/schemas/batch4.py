"""Pydantic contracts for Batch 4 identity and gate-decision workflows."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import GateDecision


# PUBLIC_INTERFACE
class GateEvaluationCreate(BaseModel):
    """A gate operator request to evaluate one opaque QR token reference."""

    token_reference: str = Field(
        ...,
        min_length=12,
        max_length=512,
        description=(
            "Opaque token reference obtained from a scanned, pasted, or seeded "
            "QR payload. It must not contain personal data."
        ),
    )
    site_id: uuid.UUID = Field(
        ...,
        description="Site at which the operator is attempting access.",
    )
    presentation_reference: str = Field(
        default="demo-presentation",
        min_length=3,
        max_length=160,
        description=(
            "Synthetic identity presentation reference evaluated only by the "
            "configured identity adapter."
        ),
    )
    comparison_confirmed: bool = Field(
        default=False,
        description=(
            "Operator explicitly confirms that the presented physical document "
            "matches the QR-bound invitation upload. Required for entry; it "
            "never substitutes for server-side eligibility checks."
        ),
    )


# PUBLIC_INTERFACE
class GatePresentationCreate(BaseModel):
    """Opaque scanned QR and operating site used for an authorized comparison."""

    token_reference: str = Field(..., min_length=12, max_length=512, description="Decoded issued QR credential; never a person or visit selector.")
    site_id: uuid.UUID = Field(..., description="Site where the gate operator is working.")


# PUBLIC_INTERFACE
class GateUploadResponse(BaseModel):
    """Minimal private upload metadata available for physical comparison."""

    id: uuid.UUID | None = Field(default=None, description="Evidence identifier, or null for the separate invitation ID.")
    kind: Literal["invitation_id", "evidence"] = Field(..., description="Private upload source.")
    label: str = Field(..., description="Document label.")
    filename: str = Field(..., description="Uploaded filename, or a generic label for the invitation ID.")
    media_type: str = Field(..., description="Stored MIME type.")
    status: str = Field(..., description="Current review state; comparison does not change this state.")


# PUBLIC_INTERFACE
class GatePresentationResponse(BaseModel):
    """Server-resolved invitee and visit context, without document bytes or QR."""

    invitation_id: uuid.UUID = Field(..., description="Invitation bound to the issued QR.")
    person_id: uuid.UUID = Field(..., description="Registered person bound to the issued QR.")
    person_name: str = Field(..., description="Registered invitee's name.")
    email: str = Field(..., description="Registered invitee's email.")
    company_name: str = Field(..., description="Registered company name.")
    population: str = Field(..., description="Registered population.")
    purpose: str = Field(..., description="Registered visit purpose.")
    site_name: str = Field(..., description="Site associated with this visit.")
    starts_at: datetime = Field(..., description="Visit start.")
    ends_at: datetime = Field(..., description="Visit end.")
    qr_valid_from: datetime | None = Field(default=None, description="When the QR starts working.")
    qr_valid_until: datetime | None = Field(default=None, description="When the QR stops working (its exit time).")
    site_timezone: str = Field(default="UTC", description="The site's time zone for showing the window.")
    uploads: list[GateUploadResponse] = Field(..., description="Uploads attached specifically to this invitation.")


# PUBLIC_INTERFACE
class GateCheckResponse(BaseModel):
    """One ordered server-calculated check used to form a gate outcome."""

    code: str = Field(..., description="Stable machine-readable check code.")
    label: str = Field(..., description="Readable check name for gate operators.")
    status: Literal["passed", "failed"] = Field(
        ...,
        description="Whether the check passed at the evaluation timestamp.",
    )
    blocking: bool = Field(
        ...,
        description="Whether a failed check prevents gate entry.",
    )
    reason_code: str | None = Field(
        default=None,
        description="Stable denial reason when this check fails.",
    )
    detail: str = Field(
        ...,
        description="Readable explanation of the current check result.",
    )
    corrective_action: str | None = Field(
        default=None,
        description="Operator-safe next action when the check fails.",
    )


# PUBLIC_INTERFACE
class IdentityVerificationResponse(BaseModel):
    """A sanitized deterministic identity result for one gate attempt."""

    match: bool
    confidence: float = Field(..., ge=0, le=1)
    mode: str = Field(..., description="Provider mode, including DEMO for mock results.")
    provider_reference: str = Field(
        ...,
        description="Sanitized provider correlation reference suitable for audit.",
    )
    evaluated_at: datetime


# PUBLIC_INTERFACE
class GateDecisionResponse(BaseModel):
    """The persisted, backend-authoritative decision for a gate attempt."""

    model_config = ConfigDict(from_attributes=True)

    gate_event_id: uuid.UUID
    decision: GateDecision
    reason_codes: list[str]
    reasons: list[str]
    corrective_actions: list[str]
    primary_reason_code: str = Field(
        ...,
        description=(
            "Highest-precedence denial reason, or ACCESS_GRANTED when every "
            "mandatory server-side check passes."
        ),
    )
    primary_reason: str = Field(
        ...,
        description="Readable explanation of the authoritative gate decision.",
    )
    next_action: str = Field(
        ...,
        description="Single operator-safe action selected by backend precedence.",
    )
    checks: list[GateCheckResponse]
    identity: IdentityVerificationResponse | None
    token_id: uuid.UUID | None
    visit_id: uuid.UUID | None
    person_id: uuid.UUID | None
    requested_site_id: uuid.UUID
    occurred_at: datetime
    token_valid_from: datetime | None = Field(default=None, description="When the presented QR starts working.")
    token_valid_until: datetime | None = Field(default=None, description="When the presented QR stops working.")
    site_timezone: str = Field(default="UTC", description="The site's time zone for showing the window.")
