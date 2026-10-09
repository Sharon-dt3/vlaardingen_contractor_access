"""Pydantic contracts for core Batch 1 records and audit events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import PersonStanding, Population, Role, VisitStatus


class SiteResponse(BaseModel):
    """Public core fields for an authorized site read."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seed_key: str
    name: str
    country_code: str
    timezone: str
    gate_mode: str
    is_active: bool


class CompanyResponse(BaseModel):
    """Public core fields for an authorized fictional-company read."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seed_key: str
    name: str
    company_type: str
    country_code: str
    is_active: bool


class PersonResponse(BaseModel):
    """Authorized synthetic-person record without credential evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seed_key: str
    company_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    population: Population
    standing: PersonStanding
    source_metadata: dict[str, Any]


# PUBLIC_INTERFACE
class PersonDeletionConfirmation(BaseModel):
    """Explicit acknowledgement of irreversible deletion of one person."""

    person_id: uuid.UUID = Field(
        ...,
        description="UUID of the person being deleted; must equal the path UUID.",
    )
    confirmation: str = Field(
        ...,
        description='Exact confirmation phrase: "DELETE PERSON".',
        examples=["DELETE PERSON"],
    )


# PUBLIC_INTERFACE
class PersonDeletionResult(BaseModel):
    """Outcome of selected-person deletion and private-object erasure."""

    person_id: uuid.UUID = Field(..., description="UUID of the deleted person.")
    shared_objects_retained: int = Field(
        ..., description="Private objects retained because unrelated records use them."
    )
    storage_objects_not_erased: int = Field(
        ..., description="Unshared private objects whose erasure failed."
    )
    limitations: list[str] = Field(
        ..., description="Erasure boundaries and any follow-up required."
    )


# PUBLIC_INTERFACE
class PersonErasureRetryResult(BaseModel):
    """Aggregate outcome of retrying one deleted person's queued objects."""

    person_id: uuid.UUID = Field(..., description="Exact deleted-person UUID.")
    storage_objects_erased: int = Field(
        ..., description="Queued objects erased during this attempt."
    )
    storage_objects_not_erased: int = Field(
        ..., description="Queued objects whose storage erasure failed."
    )
    shared_objects_retained: int = Field(
        ..., description="Queued objects still referenced by other records."
    )


class VisitResponse(BaseModel):
    """Authorized foundational visit record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seed_key: str
    person_id: uuid.UUID
    site_id: uuid.UUID
    host_person_id: uuid.UUID | None
    purpose: str
    status: VisitStatus
    starts_at: datetime
    ends_at: datetime


class AuditEventCreate(BaseModel):
    """Validated business evidence appended by an authorized command."""

    action: str = Field(
        ...,
        min_length=3,
        max_length=120,
        description="Stable dot-separated business action.",
        examples=["demo.validation.recorded"],
    )
    entity_type: str = Field(
        ...,
        min_length=2,
        max_length=80,
        description="Type of entity affected by the command.",
    )
    entity_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Opaque or stable identifier of the affected entity.",
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Human-readable reason for the business event.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Synthetic, non-secret structured context.",
    )


class AuditEventResponse(BaseModel):
    """Chronological immutable audit evidence."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str
    reason: str
    details: dict[str, Any]
    occurred_at: datetime


class RoleAccountSummary(BaseModel):
    """Minimal account representation for future role-aware clients."""

    model_config = ConfigDict(from_attributes=True)

    handle: str
    display_name: str
    role: Role
