"""Pydantic contracts for local demo authentication."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models import Role


class LoginRequest(BaseModel):
    """Credentials submitted to the deterministic local demo provider."""

    handle: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Seeded demo account handle, such as admin.demo.",
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Configured local demo seed password.",
    )


class UserResponse(BaseModel):
    """Authenticated account details and effective API permissions."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Stable account identifier.")
    handle: str = Field(..., description="Seeded account handle.")
    display_name: str = Field(..., description="Human-readable fictional account name.")
    role: Role = Field(..., description="Authoritative API role.")
    permissions: list[str] = Field(
        ...,
        description="Effective permission keys used by the API.",
    )


class SessionResponse(BaseModel):
    """Successful login result with the authenticated account."""

    user: UserResponse = Field(..., description="Authenticated demo account.")
    expires_in_seconds: int = Field(
        ...,
        description="Signed-session lifetime in seconds.",
    )
