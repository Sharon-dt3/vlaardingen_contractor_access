"""Authorized read routes for core Batch 1 records."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import Company, Person, Role, Site, UserAccount, Visit
from app.providers import StorageProvider, get_storage_provider
from app.schemas.domain import (
    CompanyResponse,
    PersonDeletionConfirmation,
    PersonDeletionResult,
    PersonErasureRetryResult,
    PersonResponse,
    SiteResponse,
    VisitResponse,
)
from app.schemas.life_saving import PersonWithLifeSavingResponse
from app.security import require_permissions
from app.services.life_saving import status_for_people
from app.services.people import delete_person_data, retry_private_erasure
from app.services.workflows import WorkflowError

router = APIRouter(prefix="/api", tags=["Core records"])


# PUBLIC_INTERFACE
@router.get(
    "/sites",
    response_model=list[SiteResponse],
    operation_id="list_sites",
    summary="List authorized sites",
    description="Returns active and inactive sites to roles with sites:read.",
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks sites:read."},
    },
)
def list_sites(
    _: Annotated[UserAccount, Depends(require_permissions("sites:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[Site]:
    """List sites in deterministic display order.

    Args:
        _: Authorized current account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        All sites ordered by name.
    """

    return list(database.scalars(select(Site).order_by(Site.name)).all())


# PUBLIC_INTERFACE
@router.get(
    "/companies",
    response_model=list[CompanyResponse],
    operation_id="list_companies",
    summary="List authorized companies",
    description="Returns fictional companies to roles with companies:read.",
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks companies:read."},
    },
)
def list_companies(
    _: Annotated[UserAccount, Depends(require_permissions("companies:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[Company]:
    """List synthetic companies in deterministic display order.

    Args:
        _: Authorized current account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        All fictional companies ordered by name.
    """

    return list(database.scalars(select(Company).order_by(Company.name)).all())


# PUBLIC_INTERFACE
@router.get(
    "/people",
    response_model=list[PersonWithLifeSavingResponse],
    operation_id="list_people",
    summary="List authorized people",
    description=(
        "Returns synthetic core person records to roles with people:read, each with "
        "whether the person has confirmed the life-saving rules now in force."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks people:read."},
    },
)
def list_people(
    _: Annotated[UserAccount, Depends(require_permissions("people:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[PersonWithLifeSavingResponse]:
    """List synthetic people without evidence or credential payloads.

    Args:
        _: Authorized current account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        People ordered by last and first name.
    """

    statement = select(Person).order_by(Person.last_name, Person.first_name)
    people = list(database.scalars(statement).all())
    statuses = status_for_people(database, [person.id for person in people])
    return [
        PersonWithLifeSavingResponse.model_validate(
            {
                **PersonResponse.model_validate(person).model_dump(),
                "life_saving_rules": statuses[person.id],
            }
        )
        for person in people
    ]


# PUBLIC_INTERFACE
@router.delete(
    "/people/{person_id}",
    response_model=PersonDeletionResult,
    operation_id="delete_person_complete_data",
    summary="Permanently delete one person's data",
    description=(
        "System administrators only. Requires the exact selected person UUID "
        "in both the path and confirmation body, plus the explicit confirmation "
        "phrase. Deletes the selected person's linked records and attempts to "
        "erase their private evidence and invitation ID files. Content-addressed "
        "files still used by other records or shared assets are retained and "
        "reported. Private-file erasure runs only after the database commit; "
        "failed erasures remain queued for administrator retry. "
        "Backups and previously orphaned files are outside this operation. "
        "This action cannot be undone."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "Only a system administrator can delete a person."},
        404: {"description": "The selected person does not exist."},
        422: {"description": "Explicit confirmation is missing or does not match."},
    },
)
def delete_person(
    person_id: uuid.UUID,
    payload: PersonDeletionConfirmation,
    actor: Annotated[UserAccount, Depends(require_permissions("people:delete"))],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
) -> PersonDeletionResult:
    """Permanently erase records owned by one selected person.

    Args:
        person_id: Exact UUID of the person selected in the UI.
        payload: Matching UUID and explicit irreversible-deletion phrase.
        actor: Authenticated system administrator.
        database: Request-scoped transactional database session.
        storage: Configured private storage provider.

    Returns:
        Database deletion outcome and aggregate private-file limitations.
    """

    try:
        objects_to_erase, shared_count = delete_person_data(
            database,
            actor=actor,
            person_id=person_id,
            confirmation=payload,
        )
        database.commit()
    except WorkflowError as error:
        database.rollback()
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except Exception:
        database.rollback()
        raise
    # Only committed queue entries may be processed; no filesystem action
    # takes place before the person deletion and queued work are durable.
    erased, failed_count, newly_retained = retry_private_erasure(
        database, actor=actor, person_id=person_id, storage=storage
    )
    shared_count += newly_retained
    return PersonDeletionResult(
        person_id=person_id,
        shared_objects_retained=shared_count,
        storage_objects_not_erased=failed_count,
        limitations=(
            (["Shared content-addressed objects remain for unrelated records or assets."] if shared_count else [])
            + (["Some private objects remain queued for administrator retry."] if failed_count else [])
            + ["Backups and previously orphaned files are outside this operation."]
        ),
    )


# PUBLIC_INTERFACE
@router.post(
    "/people/{person_id}/private-erasure/retry",
    response_model=PersonErasureRetryResult,
    operation_id="retry_person_private_erasure",
    summary="Retry queued private-file erasure for a deleted person",
    description=(
        "System administrators only. Retries persisted work for the exact "
        "deleted-person UUID, rechecking current evidence, invitation and asset "
        "references before any file removal. Returns aggregate counts only."
    ),
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "Only a system administrator may retry erasure."},
        409: {"description": "The person has not been deleted."},
    },
)
def retry_person_private_erasure(
    person_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("people:delete"))],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
) -> PersonErasureRetryResult:
    """Retry one deleted person's committed queue entries.

    Args:
        person_id: Exact UUID selected for the original deletion.
        actor: Authenticated system administrator.
        database: Request-scoped SQLAlchemy session.
        storage: Configured private storage provider.

    Returns:
        Aggregate erased, failed, and newly shared object counts.
    """

    if actor.role is not Role.SYSTEM_ADMIN:
        raise HTTPException(403, "Only a system administrator can retry erasure.")
    try:
        erased, pending, retained = retry_private_erasure(
            database, actor=actor, person_id=person_id, storage=storage
        )
    except WorkflowError as error:
        database.rollback()
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except Exception:
        database.rollback()
        raise
    return PersonErasureRetryResult(
        person_id=person_id,
        storage_objects_erased=erased,
        storage_objects_not_erased=pending,
        shared_objects_retained=retained,
    )


# PUBLIC_INTERFACE
@router.get(
    "/visits",
    response_model=list[VisitResponse],
    operation_id="list_visits",
    summary="List authorized visits",
    description="Returns foundational visit records to roles with visits:read.",
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account lacks visits:read."},
    },
)
def list_visits(
    _: Annotated[UserAccount, Depends(require_permissions("visits:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[Visit]:
    """List visits in chronological order.

    Args:
        _: Authorized current account.
        database: Request-scoped SQLAlchemy session.

    Returns:
        Visits ordered by start time and stable seed key.
    """

    statement = select(Visit).order_by(Visit.starts_at, Visit.seed_key)
    return list(database.scalars(statement).all())
