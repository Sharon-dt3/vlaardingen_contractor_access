"""Request and response shapes for staff accounts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StaffInvite(BaseModel):
    """What an administrator enters to add a person."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    role: Literal["system_admin", "gate_operator"]

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2 or any(ord(character) < 32 for character in cleaned):
            raise ValueError("Enter the person's name.")
        return cleaned


class StaffRow(BaseModel):
    """One staff account as the Users screen shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    email: str | None
    handle: str
    role: str
    status: Literal["invited", "active", "locked", "deactivated"]
    last_login_at: datetime | None = None
    is_you: bool = False


class StaffInviteResult(BaseModel):
    """The new row, and whether the email was handed to the mail server."""

    user: StaffRow
    email_sent: bool


class InvitationLookup(BaseModel):
    """Who a set-password link is for."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20, max_length=200)


class InvitationInfo(BaseModel):
    display_name: str
    email: str
    role_label: str


class SetPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20, max_length=200)
    password: str = Field(..., min_length=1, max_length=256)


class ForgotPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class ChangePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)
