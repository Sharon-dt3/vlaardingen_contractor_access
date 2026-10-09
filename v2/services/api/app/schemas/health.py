"""Health endpoint response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Readiness state for one service component."""

    status: Literal["ready", "unavailable"] = Field(
        ...,
        description="Sanitized readiness state for the component.",
    )


class HealthResponse(BaseModel):
    """Aggregate API readiness response."""

    status: Literal["ready", "degraded"] = Field(
        ...,
        description="Overall API readiness state.",
    )
    api: ComponentHealth = Field(
        ...,
        description="API process readiness.",
    )
    database: ComponentHealth = Field(
        ...,
        description="PostgreSQL query readiness.",
    )
    environment: str = Field(
        ...,
        description="Non-secret runtime environment name.",
    )
    demo_mode: bool = Field(
        ...,
        description="Whether deterministic manager-demo behavior is enabled.",
    )
    providers: dict[str, Literal["DEMO", "LOCAL", "EXTERNAL"]] = Field(
        ...,
        description="Sanitized selected provider modes.",
    )
