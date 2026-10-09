"""Pydantic contracts for Batch 6 expiry and re-validation workflows."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import EvidenceStatus, ExpirySubjectKind, RevalidationTaskStatus


# PUBLIC_INTERFACE
class DemoClockAdvanceCommand(BaseModel):
    """A privileged deterministic demo-clock advancement command."""

    days: Literal[7, 14, 30] = Field(
        ...,
        description="Permitted number of calendar days to advance the persisted demo clock.",
    )


# PUBLIC_INTERFACE
class DemoClockResponse(BaseModel):
    """The currently effective persisted demo clock instant."""

    effective_at: datetime
    updated_at: datetime
    updated_by_id: uuid.UUID | None = None


# PUBLIC_INTERFACE
class ExpiryProcessResponse(BaseModel):
    """A deterministic summary of one idempotent expiry-processing pass."""

    processed_at: datetime
    created_alert_count: int
    created_task_count: int
    existing_alert_count: int
    existing_task_count: int


# PUBLIC_INTERFACE
class ExpiryAlertResponse(BaseModel):
    """A safe persisted in-app expiry alert and delivery result."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    site_id: uuid.UUID
    requirement_id: uuid.UUID
    source_kind: ExpirySubjectKind
    source_id: uuid.UUID
    alert_code: str
    expires_at: datetime
    delivery_mode: str
    delivery_status: str
    provider_reference: str | None
    created_at: datetime
    created_by_id: uuid.UUID


# PUBLIC_INTERFACE
class RevalidationTaskResponse(BaseModel):
    """A safe representation of an actionable or completed re-validation task."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    site_id: uuid.UUID
    requirement_id: uuid.UUID
    source_kind: ExpirySubjectKind
    source_id: uuid.UUID
    status: RevalidationTaskStatus
    created_at: datetime
    completed_at: datetime | None
    completed_by_id: uuid.UUID | None


# PUBLIC_INTERFACE
class OnSiteRenewalSubmission(BaseModel):
    """A requested evidence renewal for a person currently present at the task's site."""

    person_id: uuid.UUID = Field(
        ...,
        description="Selected on-site person; must match the open re-validation task.",
    )
    expiry_date: date = Field(
        ...,
        description="User-chosen document expiry date, subject to later human verification.",
    )
    source_id: uuid.UUID = Field(
        ...,
        description="Expired evidence identifier shown on the task; prevents stale submissions.",
    )

    @model_validator(mode="after")
    def validate_expiry_date(self) -> "OnSiteRenewalSubmission":
        """Require a date, rather than silently accepting an expiry timestamp."""

        if isinstance(self.expiry_date, datetime):
            raise ValueError("Choose an expiry date without a time component.")
        return self


# PUBLIC_INTERFACE
class OnSiteRenewalResponse(BaseModel):
    """Submitted renewal awaiting review; the task and prior evidence remain unchanged."""

    evidence_id: uuid.UUID = Field(..., description="New pending evidence identifier.")
    person_id: uuid.UUID = Field(..., description="Selected on-site person identifier.")
    task_id: uuid.UUID = Field(..., description="Open task associated with the submission.")
    expiry_date: date = Field(..., description="Proposed expiry date, not yet verified.")
    status: EvidenceStatus = Field(..., description="Pending evidence review status.")


# PUBLIC_INTERFACE
class OnSiteIdRenewalSubmission(BaseModel):
    """A non-driver's proposed ID expiry, bound to a verified source document."""

    person_id: uuid.UUID = Field(
        ..., description="Person selected from the current on-site roster."
    )
    source_id: uuid.UUID = Field(
        ..., description="Currently verified ID-card evidence shown for that person."
    )
    expiry_date: date = Field(
        ..., description="Proposed future ID-card expiry, pending human verification."
    )

    @model_validator(mode="after")
    def validate_expiry_date(self) -> "OnSiteIdRenewalSubmission":
        """Reject timestamps instead of silently treating them as dates."""

        if isinstance(self.expiry_date, datetime):
            raise ValueError("Choose an expiry date without a time component.")
        return self


# PUBLIC_INTERFACE
class OnSiteIdRenewalResponse(BaseModel):
    """Pending on-site ID renewal; the verified roster date remains unchanged."""

    evidence_id: uuid.UUID = Field(..., description="New reviewable evidence identifier.")
    person_id: uuid.UUID = Field(..., description="Selected on-site person identifier.")
    source_id: uuid.UUID = Field(..., description="Previous verified ID-card identifier.")
    expiry_date: date = Field(..., description="Proposed, unverified expiry date.")
    status: EvidenceStatus = Field(..., description="Pending evidence review state.")
