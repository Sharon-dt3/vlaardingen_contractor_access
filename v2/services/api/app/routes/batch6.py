"""Authorized APIs for Batch 6 expiry, re-validation, and demo-time workflows."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import RevalidationTaskStatus, UserAccount
from app.schemas.batch6 import (
    DemoClockAdvanceCommand,
    DemoClockResponse,
    ExpiryAlertResponse,
    ExpiryProcessResponse,
    OnSiteIdRenewalResponse,
    OnSiteIdRenewalSubmission,
    OnSiteRenewalResponse,
    OnSiteRenewalSubmission,
    RevalidationTaskResponse,
)
from app.security import require_permissions
from app.services import (
    WorkflowError,
    advance_demo_clock,
    complete_revalidation_task,
    current_demo_time,
    get_effective_time,
    list_expiry_alerts,
    list_revalidation_tasks,
    process_expiry,
    submit_on_site_id_renewal,
    submit_on_site_renewal,
)


router = APIRouter(prefix="/api", tags=["Expiry and re-validation"])


def _raise_api_error(error: WorkflowError) -> None:
    """Translate a domain-service error to its documented HTTP response."""

    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _clock_response(database: Session) -> DemoClockResponse:
    """Project the effective time while representing an uninitialized clock safely."""

    persisted = current_demo_time(database)
    effective_at = persisted or get_effective_time(database)
    return DemoClockResponse(
        effective_at=effective_at,
        updated_at=effective_at,
        updated_by_id=None,
    )


# PUBLIC_INTERFACE
@router.get(
    "/demo-clock",
    response_model=DemoClockResponse,
    operation_id="get_demo_clock",
    summary="Read the persisted effective demo time",
    description=(
        "Returns the effective time used by expiry, compliance, token, and gate "
        "evaluation. Before the first privileged advancement, the API uses UTC "
        "host time without creating a clock record."
    ),
)
def get_demo_clock(
    _: Annotated[UserAccount, Depends(require_permissions("expiry:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> DemoClockResponse:
    """Return the effective deterministic demo time visible to authorized users."""

    return _clock_response(database)


# PUBLIC_INTERFACE
@router.post(
    "/demo-clock/advance",
    response_model=DemoClockResponse,
    operation_id="advance_demo_clock",
    summary="Advance the persisted demo clock",
    description=(
        "Privileged deterministic-demo command that advances time by 7, 14, or "
        "30 days. Invoke expiry processing afterward to create due alerts/tasks."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot operate the demo clock."},
        422: {"description": "The requested interval is not supported."},
    },
)
def post_demo_clock_advance(
    payload: DemoClockAdvanceCommand,
    actor: Annotated[UserAccount, Depends(require_permissions("expiry:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> DemoClockResponse:
    """Advance and persist effective demo time for deterministic expiry scenarios."""

    try:
        clock = advance_demo_clock(database, actor=actor, days=payload.days)
        database.commit()
        database.refresh(clock)
        return DemoClockResponse(
            effective_at=clock.effective_at,
            updated_at=clock.updated_at,
            updated_by_id=clock.updated_by_id,
        )
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/expiry/process",
    response_model=ExpiryProcessResponse,
    operation_id="process_expiry",
    summary="Process expiry alerts and re-validation tasks",
    description=(
        "Runs deterministic idempotent expiry processing against the effective "
        "demo clock. Durable in-app alerts and tasks are created independently "
        "of notification delivery success."
    ),
)
def post_expiry_process(
    actor: Annotated[UserAccount, Depends(require_permissions("expiry:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> ExpiryProcessResponse:
    """Process expiry state and return newly created versus existing record counts."""

    try:
        result = process_expiry(database, actor=actor)
        database.commit()
        return ExpiryProcessResponse.model_validate(result)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.get(
    "/expiry/alerts",
    response_model=list[ExpiryAlertResponse],
    operation_id="list_expiry_alerts",
    summary="List persisted in-app expiry alerts",
    description=(
        "Lists durable expiry alerts and local notification results without "
        "requiring external email or messaging delivery."
    ),
)
def get_expiry_alerts(
    _: Annotated[UserAccount, Depends(require_permissions("expiry:read"))],
    database: Annotated[Session, Depends(get_db)],
    person_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional person identifier that narrows the alert list."),
    ] = None,
) -> list[ExpiryAlertResponse]:
    """Return current and historical expiry alerts in newest-first order."""

    return [
        ExpiryAlertResponse.model_validate(alert)
        for alert in list_expiry_alerts(database, person_id=person_id)
    ]


# PUBLIC_INTERFACE
@router.get(
    "/revalidation/tasks",
    response_model=list[RevalidationTaskResponse],
    operation_id="list_revalidation_tasks",
    summary="List expiry-triggered re-validation tasks",
    description="Lists actionable and completed tasks generated from expired required items.",
)
def get_revalidation_tasks(
    _: Annotated[UserAccount, Depends(require_permissions("expiry:read"))],
    database: Annotated[Session, Depends(get_db)],
    person_id: Annotated[
        uuid.UUID | None,
        Query(description="Optional person identifier that narrows the task list."),
    ] = None,
    task_status: Annotated[
        RevalidationTaskStatus | None,
        Query(alias="status", description="Optional task lifecycle status filter."),
    ] = None,
) -> list[RevalidationTaskResponse]:
    """Return protected re-validation task records in stable actionable order."""

    return [
        RevalidationTaskResponse.model_validate(task)
        for task in list_revalidation_tasks(
            database,
            person_id=person_id,
            status=task_status,
        )
    ]


# PUBLIC_INTERFACE
@router.post(
    "/revalidation/tasks/{task_id}/renewals",
    response_model=OnSiteRenewalResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submit_on_site_renewal",
    summary="Submit an on-site person's proposed evidence renewal",
    description=(
        "Requires expiry-write permission, an open evidence task, a matching "
        "expired source, and current presence at the task's site. Records a "
        "user-chosen expiry as pending evidence for authorized review; it does "
        "not verify evidence, complete the task, or alter gate eligibility."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot submit expiry renewals."},
        404: {"description": "The task does not exist."},
        409: {"description": "Task, person, source, presence, or pending renewal conflicts."},
        422: {"description": "The proposed expiry is invalid or this is a training task."},
    },
)
def post_on_site_renewal(
    task_id: uuid.UUID,
    payload: OnSiteRenewalSubmission,
    actor: Annotated[UserAccount, Depends(require_permissions("expiry:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> OnSiteRenewalResponse:
    """Submit a proposed evidence expiry without claiming verification.

    Args:
        task_id: Identifier of the open evidence re-validation task.
        payload: Selected on-site person, expired evidence source, and expiry date.
        actor: Authenticated expiry-workflow operator.
        database: Request-scoped database transaction.

    Returns:
        Identifier and pending status of the reviewable evidence submission.
    """

    try:
        evidence = submit_on_site_renewal(
            database, actor=actor, task_id=task_id, payload=payload
        )
        database.commit()
        return OnSiteRenewalResponse(
            evidence_id=evidence.id,
            person_id=evidence.person_id,
            task_id=task_id,
            expiry_date=evidence.expiry_date,
            status=evidence.status,
        )
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/expiry/on-site-id-renewals",
    response_model=OnSiteIdRenewalResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="submit_on_site_id_renewal",
    summary="Propose a non-driver's on-site ID renewal",
    description=(
        "Requires expiry-write permission, current on-site presence, and the "
        "person's latest verified ID card. Accepts a later proposed date as "
        "unverified evidence for human review. No expiry task is required. "
        "The roster displays only verified dates; this command does not "
        "restore access or change gate eligibility."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot propose expiry renewals."},
        404: {"description": "The selected person does not exist."},
        409: {"description": "Presence, verified source, or pending renewal conflicts."},
        422: {"description": "Driver ID or proposed expiry is invalid."},
    },
)
def post_on_site_id_renewal(
    payload: OnSiteIdRenewalSubmission,
    actor: Annotated[UserAccount, Depends(require_permissions("expiry:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> OnSiteIdRenewalResponse:
    """Propose a new non-driver ID expiry subject to evidence review.

    Args:
        payload: On-site person, current verified ID, and proposed future date.
        actor: Authorized expiry-workflow operator.
        database: Request-scoped transaction.

    Returns:
        Pending evidence metadata; the verified roster date remains unchanged.
    """

    try:
        evidence = submit_on_site_id_renewal(database, actor=actor, payload=payload)
        database.commit()
        return OnSiteIdRenewalResponse(
            evidence_id=evidence.id,
            person_id=evidence.person_id,
            source_id=payload.source_id,
            expiry_date=evidence.expiry_date,
            status=evidence.status,
        )
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/revalidation/tasks/{task_id}/complete",
    response_model=RevalidationTaskResponse,
    operation_id="complete_revalidation_task",
    summary="Complete re-validation after verified renewal",
    description=(
        "Completes a task only when the current evidence or training renewal is "
        "verified and unexpired. The backend then recalculates active visit "
        "compliance; gate decisions continue to use those live checks."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot complete re-validation."},
        404: {"description": "The task does not exist."},
        409: {"description": "The task is already complete or renewal is not verified."},
    },
)
def post_revalidation_complete(
    task_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("expiry:write"))],
    database: Annotated[Session, Depends(get_db)],
) -> RevalidationTaskResponse:
    """Complete one renewed task through the authoritative current-state pathway."""

    try:
        task = complete_revalidation_task(database, actor=actor, task_id=task_id)
        database.commit()
        database.refresh(task)
        return RevalidationTaskResponse.model_validate(task)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise
