"""Authorized APIs for Batch 4 deterministic identity and gate decisions."""

from __future__ import annotations

from typing import Annotated, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import AccessToken, Site, UserAccount, Visit
from app.providers import StorageProvider, get_storage_provider
from app.schemas.batch4 import (
    GateDecisionResponse, GateEvaluationCreate, GatePresentationCreate,
    GatePresentationResponse,
)
from app.security import require_permissions
from app.services import WorkflowError, evaluate_gate_access
from app.services.batch4 import get_gate_presentation, read_gate_upload

router = APIRouter(prefix="/api", tags=["Identity and gate decisions"])


def _raise_api_error(error: WorkflowError) -> None:
    """Translate a domain-service error to its documented HTTP response."""

    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


# PUBLIC_INTERFACE
@router.post(
    "/gate/presentation",
    response_model=GatePresentationResponse,
    operation_id="get_gate_presentation",
    summary="Resolve a scanned issued QR into an authorized Gate comparison view",
    description="Returns only the registered invitee and invitation-bound upload metadata for a current issued QR at this gate site; never returns document bytes or the credential.",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Gate permission required."}, 404: {"description": "QR or invitation unavailable."}},
)
def post_gate_presentation(
    payload: GatePresentationCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("gate:evaluate"))],
    database: Annotated[Session, Depends(get_db)],
) -> GatePresentationResponse:
    """Resolve the QR and requested site for an authorized gatekeeper; return limited comparison metadata."""

    try:
        return GatePresentationResponse.model_validate(get_gate_presentation(
            database, token_reference=payload.token_reference, requested_site_id=payload.site_id
        ))
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/gate/presentation/uploads/{kind}/content",
    operation_id="preview_gate_invitation_upload",
    summary="Preview a QR-bound invitation upload at the Gate",
    description="Returns private bytes only after rechecking the active QR, operating site, accepted invitation and selected upload's association. Responses are never cacheable.",
    responses={401: {"description": "Authentication required."}, 403: {"description": "Gate permission required."}, 404: {"description": "QR or upload unavailable."}},
)
def post_gate_upload_content(
    kind: Literal["invitation_id", "evidence"],
    payload: GatePresentationCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("gate:evaluate"))],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
    evidence_id: uuid.UUID | None = None,
) -> Response:
    """Return one private invitation upload for physical comparison without exposing its storage key."""

    try:
        media_type, content = read_gate_upload(
            database, token_reference=payload.token_reference, requested_site_id=payload.site_id,
            kind=kind, evidence_id=evidence_id, storage=storage,
        )
        return Response(
            content=content, media_type=media_type,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/gate/evaluations",
    response_model=GateDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="evaluate_gate_access",
    summary="Evaluate an opaque token and identity presentation at a gate",
    description=(
        "Performs token, site, visit window, standing, blacklist, current "
        "accepted invitation, verified evidence/training, approval, explicit "
        "operator confirmation that the physical document matches the invitation "
        "upload, and deterministic identity checks in the "
        "backend. Denials use fixed backend precedence and return one primary "
        "reason with an operator-safe next action. The result is persisted as "
        "an immutable gate-event snapshot."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot operate the gate."},
        422: {"description": "The gate-evaluation command is invalid."},
    },
)
def post_gate_evaluation(
    payload: GateEvaluationCreate,
    actor: Annotated[UserAccount, Depends(require_permissions("gate:evaluate"))],
    database: Annotated[Session, Depends(get_db)],
) -> GateDecisionResponse:
    """Persist and return a backend-authoritative gate decision.

    Args:
        payload: Opaque token, requested site, synthetic presentation input,
            and explicit physical-document comparison confirmation.
        actor: Authorized gate operator or privileged user.
        database: Request-scoped SQLAlchemy session.

    Returns:
        Typed grant or denial evidence with precedence-ordered checks, a single
        primary result, and an operator-safe next action.
    """

    try:
        result = evaluate_gate_access(
            database,
            actor=actor,
            token_reference=payload.token_reference,
            requested_site_id=payload.site_id,
            presentation_reference=payload.presentation_reference,
            comparison_confirmed=payload.comparison_confirmed,
        )
        token = database.get(AccessToken, result["token_id"]) if result.get("token_id") else None
        visit_for_window = database.get(Visit, result["visit_id"]) if result.get("visit_id") else None
        site_for_window = database.get(Site, result["requested_site_id"])
        if token is not None:
            result["token_valid_from"] = token.valid_from or (
                visit_for_window.starts_at if visit_for_window else None
            )
            result["token_valid_until"] = token.expires_at
        result["site_timezone"] = site_for_window.timezone if site_for_window else "UTC"
        database.commit()
        return GateDecisionResponse.model_validate(result)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise
