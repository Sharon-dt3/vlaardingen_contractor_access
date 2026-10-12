"""Request and response shapes for QR walk-up registration."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# The same six categories as an invitation.
WalkUpPopulation = Literal[
    "renewi_driver",
    "temporary_driver",
    "external_driver",
    "maintenance_contractor",
    "permanent_contractor",
    "visitor",
]


def _clean(value: str) -> str:
    cleaned = " ".join(value.split())
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ValueError("Contains characters that are not allowed.")
    return cleaned


class WalkUpSiteResponse(BaseModel):
    """The site a QR code belongs to."""

    site_key: str
    site_name: str
    id_document_required: bool = False


class WalkUpSiteLinkResponse(WalkUpSiteResponse):
    """A site with the address its QR code opens, for staff."""

    arrival_url: str


class WalkUpRegistrationCreate(BaseModel):
    """What a person enters after scanning the QR code, and their confirmation."""

    model_config = ConfigDict(extra="forbid")

    site_key: str = Field(..., min_length=1, max_length=80)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=120)
    company_name: str = Field(..., min_length=2, max_length=180)
    email: EmailStr
    population: WalkUpPopulation = "maintenance_contractor"
    rules_version_id: uuid.UUID
    language: str = Field(..., min_length=2, max_length=16)
    confirmed: bool
    # Hidden form field that real people never fill in; filled means a bot.
    website: str = Field(default="", max_length=0)

    @field_validator("first_name", "last_name", "company_name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = _clean(value)
        if not cleaned:
            raise ValueError("Must not be empty.")
        return cleaned


class WalkUpRegistrationReceipt(BaseModel):
    """What the person sees after registering."""

    reference: str
    site_name: str
    registered_at: datetime
    rules_version: int
    language: str
    pass_qr: str
    pass_valid_from: datetime | None = None
    pass_valid_until: datetime
    # The site's time zone, so the page shows entry and exit times the way the gate sees them.
    site_timezone: str = "UTC"
    # Set when a copy of the entry QR is being emailed to the verified address.
    emailed_to: str | None = None


class WalkUpRegistrationRow(BaseModel):
    """One arrival as staff see it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    person_id: uuid.UUID
    first_name: str
    last_name: str
    company_name: str
    email: str
    population: str
    site_name: str
    registered_at: datetime
    rules_version: int
    language: str
    statement_text: str
    admitted_at: datetime | None = None
    exited_at: datetime | None = None
    email_verified: bool = False
    id_uploaded: bool = False
    id_expiry_date: date | None = None
    refusal_count: int = 0
    last_refused_at: datetime | None = None


class GateReason(BaseModel):
    """One reason a person cannot be let in."""

    code: str
    message: str


class GateLookupRequest(BaseModel):
    """What the kiosk read from the person's QR, or what the operator typed."""

    model_config = ConfigDict(extra="forbid")

    site_key: str = Field(..., min_length=1, max_length=80)
    code: str = Field(..., min_length=4, max_length=200)


class GateAdmitRequest(BaseModel):
    """The operator lets one registered person in."""

    model_config = ConfigDict(extra="forbid")

    site_key: str = Field(..., min_length=1, max_length=80)
    registration_id: uuid.UUID


class GateWalkUpResponse(BaseModel):
    """What the kiosk shows the operator about a walk-up arrival."""

    registration_id: uuid.UUID
    reference: str
    first_name: str
    last_name: str
    company_name: str
    population: str
    site_name: str
    registered_at: datetime
    pass_valid_from: datetime
    pass_valid_until: datetime
    site_timezone: str = "UTC"
    rules_version: int | None
    rules_language: str | None
    eligible: bool
    reasons: list[GateReason]
    admitted_at: datetime | None
    admitted_by: str | None
    email_verified: bool
    id_uploaded: bool = False
    id_expiry_date: date | None = None
    id_media_type: str | None = None
    id_filename: str | None = None
    exited_at: datetime | None
    refusal_count: int
    last_refused_at: datetime | None


class WalkUpVerificationRequired(BaseModel):
    """The form was accepted; a code was emailed and must be entered to finish."""

    verification_required: Literal[True] = True
    pending_id: uuid.UUID
    email_hint: str
    code_expires_at: datetime
    resend_available_at: datetime


class WalkUpVerifyRequest(BaseModel):
    """The code the person received."""

    model_config = ConfigDict(extra="forbid")

    pending_id: uuid.UUID
    code: str = Field(..., pattern=r"^\d{6}$")


class WalkUpResendRequest(BaseModel):
    """Ask for another code for a registration still waiting."""

    model_config = ConfigDict(extra="forbid")

    pending_id: uuid.UUID


class GateExitRequest(BaseModel):
    """The operator records that a person has left."""

    model_config = ConfigDict(extra="forbid")

    site_key: str = Field(..., min_length=1, max_length=80)
    registration_id: uuid.UUID


class WalkUpOnSiteRow(BaseModel):
    """One walk-up person currently on site."""

    registration_id: uuid.UUID
    reference: str
    person_id: uuid.UUID
    first_name: str
    last_name: str
    company_name: str
    population: str
    site_name: str
    site_key: str
    admitted_at: datetime
    admitted_by: str | None
    exit_due_at: datetime
    overdue: bool
    overdue_minutes: int | None = None


class GateRefuseRequest(BaseModel):
    """The officer turns a person away and says why."""

    model_config = ConfigDict(extra="forbid")

    site_key: str = Field(..., min_length=1, max_length=80)
    registration_id: uuid.UUID
    reason: Literal["identity_mismatch", "not_expected", "other"]
    note: str = Field(default="", max_length=200)
