"""APIs for reading the life-saving rules, confirming them, and seeing who has."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Person, UserAccount
from app.schemas.life_saving import (
    LifeSavingConfirmationCreate,
    LifeSavingConfirmationResponse,
    LifeSavingPersonResponse,
    LifeSavingRulesResponse,
)
from app.security import require_permissions
from app.services.life_saving import (
    confirm_rules_by_invitee,
    get_current_rules,
    history_for_person,
    rules_for_display,
    status_for_people,
)
from app.services.workflows import WorkflowError

router = APIRouter(prefix="/api", tags=["Life-saving rules"])


def _raise_api_error(error: WorkflowError) -> None:
    """Translate a domain-service error to its documented HTTP response."""

    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


# PUBLIC_INTERFACE
@router.get(
    "/life-saving-rules/current",
    response_model=LifeSavingRulesResponse,
    operation_id="get_current_life_saving_rules",
    summary="Read the life-saving rules currently in force",
    description=(
        "Public: the rules are shown to a contractor before they have an account. "
        "Returns the requested language, falling back to English."
    ),
    responses={404: {"description": "No rules have been published."}},
)
def get_current_life_saving_rules(
    database: Annotated[Session, Depends(get_db)],
    response: Response,
    language: Annotated[str, Query(min_length=2, max_length=16)] = "en",
) -> LifeSavingRulesResponse:
    """Return the current rules in one language."""

    response.headers["Cache-Control"] = "no-store"
    try:
        return LifeSavingRulesResponse.model_validate(
            rules_for_display(get_current_rules(database), language)
        )
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/invitations/registration/life-saving-confirmation",
    response_model=LifeSavingConfirmationResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="confirm_life_saving_rules",
    summary="Confirm that the contractor read and understood the life-saving rules",
    description=(
        "Made by the contractor themselves with their private registration link, "
        "after registering. Staff cannot confirm on someone's behalf. The exact "
        "wording confirmed, the rules version and the time are stored and audited. "
        "Confirming the same version again returns the existing record."
    ),
    responses={
        404: {"description": "Invalid link, or unknown rules version."},
        409: {"description": "Registration is incomplete, or the rules have been updated."},
        410: {"description": "Registration link expired."},
        422: {"description": "The confirmation box was not ticked."},
    },
)
def post_life_saving_confirmation(
    payload: LifeSavingConfirmationCreate,
    database: Annotated[Session, Depends(get_db)],
    response: Response,
) -> LifeSavingConfirmationResponse:
    """Record the contractor's confirmation."""

    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        acknowledgement = confirm_rules_by_invitee(
            database,
            token=payload.token,
            rules_version_id=payload.rules_version_id,
            language=payload.language,
            confirmed=payload.confirmed,
        )
        rules_version = status_for_people(database, [acknowledgement.person_id])[
            acknowledgement.person_id
        ]["confirmed_rules_version"]
        database.commit()
        return LifeSavingConfirmationResponse(
            rules_version=rules_version or 0,
            language=acknowledgement.language,
            acknowledged_at=acknowledgement.acknowledged_at,
        )
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.get(
    "/people/{person_id}/life-saving-rules",
    response_model=LifeSavingPersonResponse,
    operation_id="get_person_life_saving_rules",
    summary="See whether a person confirmed the life-saving rules",
    description="For authorized staff: current status plus every recorded confirmation with its wording.",
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks people:read."},
        404: {"description": "The person does not exist."},
    },
)
def get_person_life_saving_rules(
    person_id: uuid.UUID,
    _: Annotated[UserAccount, Depends(require_permissions("people:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> LifeSavingPersonResponse:
    """Return one person's status and history."""

    if database.get(Person, person_id) is None:
        raise HTTPException(status_code=404, detail="Person not found.")
    return LifeSavingPersonResponse(
        person_id=person_id,
        status=status_for_people(database, [person_id])[person_id],
        history=history_for_person(database, person_id),
    )
