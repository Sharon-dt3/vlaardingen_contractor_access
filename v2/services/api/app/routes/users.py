"""The Users screen: administrators add people, who set their own passwords."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import UserAccount
from app.providers.staff_email import StaffEmailError, send_staff_invitation_email
from app.rate_limit import RateLimiter
from app.schemas.users import (
    InvitationInfo,
    InvitationLookup,
    SetPassword,
    StaffInvite,
    StaffInviteResult,
    StaffRow,
)
from app.security import require_permissions
from app.services.accounts import (
    INVITE_VALID_HOURS,
    ROLE_LABELS,
    accept_invitation,
    invite_staff,
    list_accounts,
    look_up_invitation,
    resend_invitation,
    set_active,
    status_of,
)
from app.services.workflows import WorkflowError

router = APIRouter(tags=["Staff accounts"])
_LOGGER = logging.getLogger(__name__)
_link_limiter = RateLimiter(limit=30, window_seconds=600)


def _row(account: UserAccount, viewer: UserAccount | None = None) -> StaffRow:
    return StaffRow(
        id=account.id,
        display_name=account.display_name,
        email=account.email,
        handle=account.handle,
        role=account.role.value,
        status=status_of(account),
        last_login_at=account.last_login_at,
        is_you=viewer is not None and viewer.id == account.id,
    )


def _error(error: WorkflowError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _send_invitation(account: UserAccount, secret: str, actor: UserAccount) -> bool:
    """Hand the invitation to the mail server. The link is never returned to the administrator."""

    settings = get_settings()
    if settings.notification_provider != "smtp":
        return False
    link = f"{settings.web_origin.rstrip('/')}/set-password?token={secret}"
    try:
        send_staff_invitation_email(
            settings,
            to=account.email or "",
            name=account.display_name,
            role_label=ROLE_LABELS[account.role],
            invited_by=actor.display_name,
            link=link,
            valid_hours=INVITE_VALID_HOURS,
        )
    except StaffEmailError:
        _LOGGER.warning("Staff invitation email could not be sent for account %s.", account.id)
        return False
    return True


# PUBLIC_INTERFACE
@router.get(
    "/api/users",
    response_model=list[StaffRow],
    operation_id="list_staff",
    summary="Staff accounts",
    description="Administrators only: everyone who can sign in, with their role and status.",
)
def get_users(
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[StaffRow]:
    """List every account."""

    return [_row(account, actor) for account in list_accounts(database)]


# PUBLIC_INTERFACE
@router.post(
    "/api/users",
    response_model=StaffInviteResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="invite_staff",
    summary="Add a person and email them an invitation",
    description=(
        "Administrators only. Creates an inactive account and emails a link, valid once for "
        f"{INVITE_VALID_HOURS} hours, where the person chooses their own password. "
        "The administrator never sees the link or the password."
    ),
    responses={409: {"description": "That email already has an account."}},
)
def post_user(
    payload: StaffInvite,
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> StaffInviteResult:
    """Add a person."""

    try:
        account, secret = invite_staff(
            database, actor=actor, name=payload.name, email=str(payload.email), role_key=payload.role
        )
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _error(error)
    return StaffInviteResult(user=_row(account, actor), email_sent=_send_invitation(account, secret, actor))


# PUBLIC_INTERFACE
@router.post(
    "/api/users/{account_id}/resend-invitation",
    response_model=StaffInviteResult,
    operation_id="resend_staff_invitation",
    summary="Send a new invitation",
    description="Administrators only. The earlier link stops working.",
)
def post_resend(
    account_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> StaffInviteResult:
    """Send a fresh invitation."""

    try:
        account, secret = resend_invitation(database, actor=actor, account_id=account_id)
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _error(error)
    return StaffInviteResult(user=_row(account, actor), email_sent=_send_invitation(account, secret, actor))


def _change(account_id: uuid.UUID, actor: UserAccount, database: Session, active: bool) -> StaffRow:
    try:
        account = set_active(database, actor=actor, account_id=account_id, active=active)
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _error(error)
    return _row(account, actor)


# PUBLIC_INTERFACE
@router.post("/api/users/{account_id}/deactivate", response_model=StaffRow, operation_id="deactivate_staff", summary="Deactivate an account")
def post_deactivate(
    account_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> StaffRow:
    """Block sign-in at once; the account stays so the audit trail keeps the name."""

    return _change(account_id, actor, database, False)


# PUBLIC_INTERFACE
@router.post("/api/users/{account_id}/reactivate", response_model=StaffRow, operation_id="reactivate_staff", summary="Reactivate an account")
def post_reactivate(
    account_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> StaffRow:
    """Allow sign-in again."""

    return _change(account_id, actor, database, True)


# PUBLIC_INTERFACE
@router.post(
    "/auth/invitation",
    response_model=InvitationInfo,
    operation_id="look_up_invitation",
    summary="Who is a set-password link for",
    description="Public: the page shows the name and email before asking for a password. The link is sent in the body, not the address.",
    responses={404: {"description": "The link has expired or was already used."}},
)
def post_invitation_lookup(
    payload: InvitationLookup,
    request: Request,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> InvitationInfo:
    """Check a link without using it up."""

    response.headers["Cache-Control"] = "no-store"
    if not _link_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        account = look_up_invitation(database, payload.token)
    except WorkflowError as error:
        _error(error)
    return InvitationInfo(
        display_name=account.display_name, email=account.email or "", role_label=ROLE_LABELS[account.role]
    )


# PUBLIC_INTERFACE
@router.post(
    "/auth/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="set_password",
    summary="Choose a password from an invitation",
    description="Public: spends the link, sets the person's own password and activates the account.",
    responses={404: {"description": "The link has expired or was already used."}, 422: {"description": "The password is not acceptable."}},
)
def post_set_password(
    payload: SetPassword,
    request: Request,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> Response:
    """Activate the account."""

    if not _link_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        accept_invitation(database, secret=payload.token, password=payload.password)
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _error(error)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
