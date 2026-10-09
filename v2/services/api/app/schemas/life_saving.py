"""Contracts for the life-saving rules and their confirmation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.domain import PersonResponse


# PUBLIC_INTERFACE
class LifeSavingRuleItem(BaseModel):
    """One rule the person reads before confirming."""

    title: str
    text: str


# PUBLIC_INTERFACE
class LifeSavingRulesResponse(BaseModel):
    """The current rules in one language, exactly as the person sees them."""

    id: uuid.UUID = Field(..., description="Identifier of the rules version being shown.")
    version: int = Field(..., description="Human-readable version number.")
    language: str = Field(..., description="Language actually returned.")
    available_languages: list[str] = Field(..., description="Languages this version is published in.")
    title: str
    intro: str
    rules: list[LifeSavingRuleItem]
    statement: str = Field(..., description="The exact sentence the person confirms.")
    is_sample: bool = Field(..., description="True while the text is placeholder wording.")


# PUBLIC_INTERFACE
class LifeSavingConfirmationCreate(BaseModel):
    """The contractor's own confirmation, made with their registration link."""

    token: str = Field(..., min_length=32, max_length=256, description="Registration link capability.")
    rules_version_id: uuid.UUID = Field(..., description="The rules version that was displayed.")
    language: str = Field(..., min_length=2, max_length=16, description="Language that was displayed.")
    confirmed: bool = Field(..., description="Must be true: the person read and understood the rules.")


# PUBLIC_INTERFACE
class LifeSavingConfirmationResponse(BaseModel):
    """Minimal receipt for the contractor. It reveals nothing about other people."""

    rules_version: int
    language: str
    acknowledged_at: datetime


# PUBLIC_INTERFACE
class LifeSavingStatus(BaseModel):
    """What the site sees: has this person confirmed the current life-saving rules?"""

    model_config = ConfigDict(from_attributes=True)

    status: Literal["confirmed", "not_confirmed", "outdated"] = Field(
        ...,
        description=(
            "confirmed: confirmed the current version. outdated: confirmed an older "
            "version only. not_confirmed: has never confirmed."
        ),
    )
    current_rules_version: int | None = Field(default=None, description="Version in force now.")
    confirmed_rules_version: int | None = Field(default=None, description="Version last confirmed.")
    language: str | None = None
    acknowledged_at: datetime | None = None
    method: str | None = None


# PUBLIC_INTERFACE
class PersonWithLifeSavingResponse(PersonResponse):
    """A person record plus whether they confirmed the life-saving rules in force."""

    life_saving_rules: LifeSavingStatus


# PUBLIC_INTERFACE
class LifeSavingHistoryItem(BaseModel):
    """One recorded confirmation, with the wording the person confirmed."""

    id: uuid.UUID
    rules_version: int
    language: str
    statement_text: str
    acknowledged_at: datetime
    method: str


# PUBLIC_INTERFACE
class LifeSavingPersonResponse(BaseModel):
    """A person's current status and full confirmation history, for authorized staff."""

    person_id: uuid.UUID
    status: LifeSavingStatus
    history: list[LifeSavingHistoryItem]
