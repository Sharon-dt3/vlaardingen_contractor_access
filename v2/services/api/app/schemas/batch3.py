"""Pydantic contracts for Batch 3 training, compliance, approval, and tokens."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    AccessTokenStatus,
    ApprovalDecision,
    BlacklistSubjectType,
    ComplianceRequirementKind,
    EvidenceType,
    TrainingOutcome,
)


# PUBLIC_INTERFACE
class TrainingQuestionResponse(BaseModel):
    """A safe training question that never exposes its correct answer."""

    id: str
    prompt: str
    options: list[str]


# PUBLIC_INTERFACE
class TrainingModuleResponse(BaseModel):
    """The metadata and safe question set for an active training module."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    language: str
    passing_score: int
    validity_days: int
    questions: list[TrainingQuestionResponse]
    is_active: bool


# PUBLIC_INTERFACE
class TrainingAttemptCreate(BaseModel):
    """Answers submitted for a scored training module attempt."""

    answers: dict[str, int] = Field(
        ...,
        min_length=1,
        description="Question identifiers mapped to selected zero-based option indexes.",
    )


# PUBLIC_INTERFACE
class TrainingCompletionCreate(BaseModel):
    """Administrator confirmation that both required modules were completed."""

    sheq_basics: bool = Field(
        ..., description="Administrator confirms completion of SHEQ Basics."
    )
    vlaardingen_site_rules: bool = Field(
        ..., description="Administrator confirms completion of Vlaardingen Site Rules."
    )


# PUBLIC_INTERFACE
class TrainingResultResponse(BaseModel):
    """A persisted scored training attempt without answer-key disclosure."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    training_module_id: uuid.UUID
    attempt_number: int
    score: int
    outcome: TrainingOutcome
    completed_at: datetime
    expires_at: datetime | None


# PUBLIC_INTERFACE
class BlacklistCreate(BaseModel):
    """A command to add a person or company to the authoritative blacklist."""

    subject_type: BlacklistSubjectType = Field(
        ...,
        description="Whether the blacklist applies to a person or company.",
    )
    person_id: uuid.UUID | None = Field(
        default=None,
        description="Target person identifier when subject_type is person.",
    )
    company_id: uuid.UUID | None = Field(
        default=None,
        description="Target company identifier when subject_type is company.",
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Human-readable reason retained in the audit history.",
    )
    ends_at: datetime | None = Field(
        default=None,
        description="Optional timezone-aware end time for a temporary blacklist.",
    )

    @model_validator(mode="after")
    def validate_subject(self) -> "BlacklistCreate":
        """Require exactly the target type named by subject_type."""

        has_person = self.person_id is not None
        has_company = self.company_id is not None
        if has_person == has_company:
            raise ValueError("Provide exactly one of person_id or company_id.")
        if self.subject_type is BlacklistSubjectType.PERSON and not has_person:
            raise ValueError("person_id is required for a person blacklist.")
        if self.subject_type is BlacklistSubjectType.COMPANY and not has_company:
            raise ValueError("company_id is required for a company blacklist.")
        return self


# PUBLIC_INTERFACE
class BlacklistRevokeCommand(BaseModel):
    """A documented command to revoke an active blacklist entry."""

    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Reason for ending the blacklist entry.",
    )


# PUBLIC_INTERFACE
class BlacklistResponse(BaseModel):
    """A safe representation of a blacklist record and its lifecycle."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: BlacklistSubjectType
    person_id: uuid.UUID | None
    company_id: uuid.UUID | None
    reason: str
    is_active: bool
    starts_at: datetime
    ends_at: datetime | None
    created_by_id: uuid.UUID
    revoked_by_id: uuid.UUID | None
    revoked_at: datetime | None


# PUBLIC_INTERFACE
class ComplianceCheckResponse(BaseModel):
    """One server-calculated compliance check used for approval decisions."""

    code: str
    label: str
    kind: ComplianceRequirementKind | Literal["blacklist"]
    status: Literal["passed", "missing", "expired", "failed", "blocked"]
    blocking: bool
    detail: str
    requirement_id: uuid.UUID | None = None


# PUBLIC_INTERFACE
class ComplianceEvaluationResponse(BaseModel):
    """The complete current compliance evaluation for a site visit."""

    visit_id: uuid.UUID
    person_id: uuid.UUID
    evaluated_at: datetime
    eligible: bool
    checks: list[ComplianceCheckResponse]


# PUBLIC_INTERFACE
class ApprovalEvaluationCreate(BaseModel):
    """A command that snapshots current server-side compliance for a visit."""

    reason: str = Field(
        default="Compliance evaluation requested.",
        min_length=3,
        max_length=1000,
        description="Reason for initiating an approval evaluation.",
    )


# PUBLIC_INTERFACE
class ApprovalDecisionCommand(BaseModel):
    """A reviewer decision applied to a pending approval evaluation."""

    decision: Literal["approved", "rejected", "correction_requested"] = Field(
        ...,
        description="Final reviewer decision; approval requires an eligible snapshot.",
    )
    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Decision rationale retained in the approval and audit history.",
    )


# PUBLIC_INTERFACE
class ApprovalResponse(BaseModel):
    """An auditable approval evaluation, decision, and compliance snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID
    decision: ApprovalDecision
    compliance_snapshot: list[ComplianceCheckResponse]
    reason: str
    evaluated_by_id: uuid.UUID
    decided_by_id: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None


# PUBLIC_INTERFACE
class TokenIssueCommand(BaseModel):
    """A command to issue one eligible visit-bound opaque access token."""

    expires_at: datetime | None = Field(
        default=None,
        description="Optional timezone-aware expiry no later than the visit end.",
    )
    valid_from: datetime | None = Field(
        default=None,
        description="Optional timezone-aware entry time, not before the visit start and before the expiry.",
    )


# PUBLIC_INTERFACE
class TokenRevokeCommand(BaseModel):
    """A documented command that revokes an issued opaque access token."""

    reason: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Reason stored with the token revocation audit event.",
    )


# PUBLIC_INTERFACE
class AccessTokenResponse(BaseModel):
    """Safe token metadata that never reveals its opaque lookup reference."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID
    status: AccessTokenStatus
    issued_by_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    valid_from: datetime | None = None
    revoked_by_id: uuid.UUID | None
    revoked_at: datetime | None
    revoke_reason: str | None


# PUBLIC_INTERFACE
class TokenIssueResponse(BaseModel):
    """Issued token metadata and one-time opaque QR payload for rendering."""

    token: AccessTokenResponse
    valid_from: datetime | None = Field(
        default=None, description="When entry opens: the start of the approved visit window."
    )
    site_timezone: str = Field(default="UTC", description="The site's time zone for showing the window.")
    qr_payload: str = Field(
        ...,
        description="Opaque non-guessable QR payload containing no personal data.",
    )
    delivery_status: Literal["smtp_sent", "smtp_failed", "local_only", "unavailable"] = Field(
        ...,
        description=(
            "SMTP handoff result for the accepted invitation recipient; local_only "
            "means SMTP is not configured, and unavailable means no matching accepted "
            "invitation exists. Neither status implies gate admission."
        ),
    )
