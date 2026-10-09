"""Authorized APIs for Batch 3 training, compliance, approval, and token workflows."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import AccessToken, Approval, BlacklistEntry, Invitation, Site, TrainingModule, TrainingResult, UserAccount, Visit
from app.providers.invitation_email import InvitationEmailError, send_access_token_email
from app.schemas.batch3 import (
    AccessTokenResponse,
    ApprovalDecisionCommand,
    ApprovalEvaluationCreate,
    ApprovalResponse,
    BlacklistCreate,
    BlacklistResponse,
    BlacklistRevokeCommand,
    ComplianceEvaluationResponse,
    TokenIssueCommand,
    TokenIssueResponse,
    TrainingAttemptCreate,
    TrainingCompletionCreate,
    TrainingModuleResponse,
    TrainingResultResponse,
)
from app.security import require_permissions
from app.services import (
    WorkflowError,
    create_approval_evaluation,
    create_blacklist_entry,
    decide_approval,
    evaluate_visit_compliance,
    issue_access_token,
    list_blacklist_entries,
    list_training_modules,
    list_training_results,
    list_visit_tokens,
    revoke_access_token,
    revoke_blacklist_entry,
    submit_training_attempt,
)
from app.services.batch3 import submit_training_completion

router = APIRouter(prefix="/api", tags=["Training, compliance, approvals, and tokens"])


def _raise_api_error(error: WorkflowError) -> None:
    """Translate a domain-service error to its documented HTTP response."""

    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _commit_and_refresh(database: Session, entity: object) -> object:
    """Commit a workflow mutation and refresh its persisted representation."""

    database.commit()
    database.refresh(entity)
    return entity


# PUBLIC_INTERFACE
@router.get(
    "/training/modules",
    response_model=list[TrainingModuleResponse],
    operation_id="list_training_modules",
    summary="List active scored training modules",
    description="Returns safe module metadata and questions without answer keys.",
)
def get_training_modules(
    _: Annotated[UserAccount, Depends(require_permissions("training:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[TrainingModuleResponse]:
    """Return active scored modules available to authorized users."""

    return [
        TrainingModuleResponse.model_validate(module)
        for module in list_training_modules(database)
    ]


# PUBLIC_INTERFACE
@router.get(
    "/people/{person_id}/training-results",
    response_model=list[TrainingResultResponse],
    operation_id="list_training_results",
    summary="List a person's scored training attempts",
    description="Participants can read only their own results; privileged roles can read all.",
)
def get_training_results(
    person_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("training:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[TrainingResult]:
    """Return authorized scored attempts in newest-first order."""

    try:
        return list_training_results(database, actor=actor, person_id=person_id)
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/people/{person_id}/training-modules/{module_id}/attempts",
    response_model=TrainingResultResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submit_training_attempt",
    summary="Score and persist a training attempt",
    description="Calculates score, pass or fail outcome, retry number, completion, expiry, and audit evidence.",
    responses={
        403: {"description": "The account cannot complete training for this person."},
        404: {"description": "The person or training module does not exist."},
        422: {"description": "Answers are incomplete or invalid."},
    },
)
def post_training_attempt(
    person_id: uuid.UUID,
    module_id: uuid.UUID,
    payload: TrainingAttemptCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("training:complete"))],
    database: Annotated[Session, Depends(get_db)],
) -> TrainingResult:
    """Score one answer set and persist the resulting immutable attempt."""

    try:
        result = submit_training_attempt(
            database,
            actor=actor,
            person_id=person_id,
            module_id=module_id,
            payload=payload,
        )
        return _commit_and_refresh(database, result)  # type: ignore[return-value]
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/people/{person_id}/training-completion",
    response_model=list[TrainingResultResponse],
    status_code=status.HTTP_201_CREATED,
    operation_id="submit_admin_training_completion",
    summary="Submit administrator-confirmed training",
    description=(
        "An administrator confirms both SHEQ Basics and Vlaardingen Site Rules "
        "were completed. Both selections are mandatory; the API records two "
        "audited results atomically."
    ),
    responses={
        403: {"description": "The account is not a system administrator."},
        404: {"description": "The person does not exist."},
        409: {"description": "A required training module is inactive or missing."},
        422: {"description": "Both confirmations must be selected."},
    },
)
def post_training_completion(
    person_id: uuid.UUID,
    payload: TrainingCompletionCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("training:complete"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[TrainingResult]:
    """Submit two administrator-confirmed module completions.

    Args:
        person_id: Participant whose prior training is being confirmed.
        payload: Confirmation flags for both required modules.
        actor: Authenticated account with training permission and admin role.
        database: Request-scoped database session.
    Returns:
        Both persisted training results, without answer keys.
    """

    try:
        results = submit_training_completion(
            database, actor=actor, person_id=person_id, payload=payload
        )
        database.commit()
        for result in results:
            database.refresh(result)
        return results
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.get(
    "/blacklist",
    response_model=list[BlacklistResponse],
    operation_id="list_blacklist_entries",
    summary="List blacklist entries",
    description="Returns active and historical blacklist records to compliance managers.",
)
def get_blacklist(
    _: Annotated[UserAccount, Depends(require_permissions("blacklist:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[BlacklistEntry]:
    """Return blacklist records with their auditable revocation state."""

    return list_blacklist_entries(database)


# PUBLIC_INTERFACE
@router.post(
    "/blacklist",
    response_model=BlacklistResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_blacklist_entry",
    summary="Create an active blacklist entry",
    description="Adds an authoritative person or company blacklist entry and audit event.",
)
def post_blacklist(
    payload: BlacklistCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("blacklist:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> BlacklistEntry:
    """Create one active blacklist entry after target validation."""

    try:
        entry = create_blacklist_entry(database, actor=actor, payload=payload)
        return _commit_and_refresh(database, entry)  # type: ignore[return-value]
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/blacklist/{entry_id}/revoke",
    response_model=BlacklistResponse,
    operation_id="revoke_blacklist_entry",
    summary="Revoke an active blacklist entry",
    description="Ends a blacklist record without deleting its historical evidence.",
)
def post_blacklist_revoke(
    entry_id: uuid.UUID,
    payload: BlacklistRevokeCommand,
    actor: Annotated[UserAccount, Depends(require_permissions("blacklist:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> BlacklistEntry:
    """End one active blacklist entry and append audit evidence."""

    try:
        entry = revoke_blacklist_entry(
            database,
            actor=actor,
            entry_id=entry_id,
            reason=payload.reason,
        )
        return _commit_and_refresh(database, entry)  # type: ignore[return-value]
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.get(
    "/visits/{visit_id}/compliance",
    response_model=ComplianceEvaluationResponse,
    operation_id="evaluate_visit_compliance",
    summary="Evaluate current visit compliance",
    description="Returns API-authoritative configurable requirement and blacklist checks.",
)
def get_visit_compliance(
    visit_id: uuid.UUID,
    _: Annotated[UserAccount, Depends(require_permissions("compliance:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> ComplianceEvaluationResponse:
    """Resolve the current compliance state for one visit."""

    try:
        return ComplianceEvaluationResponse.model_validate(
            evaluate_visit_compliance(database, visit_id=visit_id)
        )
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/visits/{visit_id}/approvals",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_approval_evaluation",
    summary="Create an approval evaluation",
    description="Snapshots current server-side compliance as a pending auditable approval.",
)
def post_approval_evaluation(
    visit_id: uuid.UUID,
    payload: ApprovalEvaluationCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("approvals:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> Approval:
    """Create a pending approval evaluation for the selected visit."""

    try:
        approval = create_approval_evaluation(
            database,
            actor=actor,
            visit_id=visit_id,
            reason=payload.reason,
        )
        return _commit_and_refresh(database, approval)  # type: ignore[return-value]
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalResponse,
    operation_id="decide_approval",
    summary="Record an approval decision",
    description="Approves only unblocked compliance snapshots and audits every decision.",
)
def post_approval_decision(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionCommand,
    actor: Annotated[UserAccount, Depends(require_permissions("approvals:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> Approval:
    """Apply an authorized reviewer decision to one pending approval."""

    from app.models import ApprovalDecision

    try:
        approval = decide_approval(
            database,
            actor=actor,
            approval_id=approval_id,
            decision=ApprovalDecision(payload.decision),
            reason=payload.reason,
        )
        return _commit_and_refresh(database, approval)  # type: ignore[return-value]
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.get(
    "/visits/{visit_id}/tokens",
    response_model=list[AccessTokenResponse],
    operation_id="list_visit_tokens",
    summary="List visit token metadata",
    description="Returns safe token metadata without opaque lookup references.",
)
def get_visit_tokens(
    visit_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("tokens:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[AccessToken]:
    """List tokens after role and participant-ownership checks."""

    try:
        return list_visit_tokens(database, actor=actor, visit_id=visit_id)
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/visits/{visit_id}/tokens",
    response_model=TokenIssueResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="issue_access_token",
    summary="Issue an opaque visit access token",
    description=(
        "Issues a token only for a currently eligible visit with an approved decision. "
        "When SMTP is configured, sends a downloadable gate-compatible QR PNG only "
        "to the accepted invitation recipient. The response reports delivery status "
        "and reveals the QR payload only once, even if SMTP fails."
    ),
)
def post_visit_token(
    visit_id: uuid.UUID,
    payload: TokenIssueCommand,
    actor: Annotated[UserAccount, Depends(require_permissions("tokens:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> TokenIssueResponse:
    """Issue and optionally email a one-time QR payload.

    Args:
        visit_id: Approved, currently eligible visit identifier.
        payload: Optional timezone-aware expiry.
        actor: Authorized issuer.
        database: Request-scoped transactional session.
    Returns:
        Issued token, one-time reference, and safe email delivery outcome.
    """

    try:
        token, qr_payload = issue_access_token(
            database,
            actor=actor,
            visit_id=visit_id,
            requested_expiry=payload.expires_at,
        )
        visit = database.get(Visit, visit_id)
        invitation = database.scalar(
            select(Invitation).where(
                Invitation.visit_id == visit_id,
                Invitation.person_id == visit.person_id,
                Invitation.site_id == visit.site_id,
                Invitation.response_status == "accepted",
            )
        )
        # Do not send a bearer credential to an unrelated contact or person.
        # A missing invitation does not weaken the existing issuance contract.
        site = database.get(Site, visit.site_id) if invitation else None
        _commit_and_refresh(database, token)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)

    delivery_status = "unavailable"
    if invitation is not None and site is not None:
        settings = get_settings()
        settings.prepare_local_runtime()
        if settings.notification_provider == "smtp":
            try:
                send_access_token_email(settings, invitation, site, token, qr_payload)
            except InvitationEmailError:
                delivery_status = "smtp_failed"
            else:
                delivery_status = "smtp_sent"
        else:
            delivery_status = "local_only"
    return TokenIssueResponse(
        token=AccessTokenResponse.model_validate(token),
        qr_payload=qr_payload,
        delivery_status=delivery_status,
    )


# PUBLIC_INTERFACE
@router.post(
    "/tokens/{token_id}/revoke",
    response_model=AccessTokenResponse,
    operation_id="revoke_access_token",
    summary="Revoke an active access token",
    description="Revokes a token without deleting its historical token or audit record.",
)
def post_token_revoke(
    token_id: uuid.UUID,
    payload: BlacklistRevokeCommand,
    actor: Annotated[UserAccount, Depends(require_permissions("tokens:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> AccessToken:
    """Revoke one active token with a documented business reason."""

    try:
        token = revoke_access_token(
            database,
            actor=actor,
            token_id=token_id,
            reason=payload.reason,
        )
        return _commit_and_refresh(database, token)  # type: ignore[return-value]
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
