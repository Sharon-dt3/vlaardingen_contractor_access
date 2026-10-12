"""The Users screen: administrators add people, who set their own passwords."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import UserAccount
from app.providers.staff_email import (
    StaffEmailError,
    send_password_changed_email,
    send_staff_invitation_email,
    send_staff_reset_email,
)
from app.rate_limit import RateLimiter
from app.schemas.users import (
    ChangePassword,
    ForgotPassword,
    InvitationInfo,
    InvitationLookup,
    SetPassword,
    StaffInvite,
    StaffInviteResult,
    StaffRow,
)
from app.security import create_session_token, get_current_user, require_permissions, verify_password
from app.services.accounts import (
    INVITE_VALID_HOURS,
    RESET_VALID_HOURS,
    change_password,
    complete_reset,
    look_up_reset,
    request_reset,
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


def _send_reset(email: str, name: str, secret: str, by_admin: bool) -> bool:
    settings = get_settings()
    if settings.notification_provider != "smtp":
        return False
    try:
        send_staff_reset_email(
            settings,
            to=email,
            name=name,
            link=f"{settings.web_origin.rstrip('/')}/reset-password?token={secret}",
            valid_minutes=RESET_VALID_HOURS * 60,
            sent_by_admin=by_admin,
        )
    except StaffEmailError:
        _LOGGER.warning("A password reset email could not be sent.")
        return False
    return True


def _send_changed_notice(email: str, name: str) -> None:
    settings = get_settings()
    if settings.notification_provider != "smtp" or not email:
        return
    try:
        send_password_changed_email(settings, to=email, name=name)
    except StaffEmailError:
        _LOGGER.warning("A password-changed notice could not be sent.")


def _forgot_in_background(email: str) -> None:
    """Look the address up and send the link after the reply, so the reply cannot give it away."""

    from app.database.session import SessionLocal

    with SessionLocal() as database:
        try:
            made = request_reset(database, email=email)
            database.commit()
        except Exception:  # noqa: BLE001 - never let a background failure show on the page
            database.rollback()
            _LOGGER.warning("A password reset request could not be processed.")
            return
        if made is not None:
            account, secret = made
            _send_reset(account.email or "", account.display_name, secret, False)


# PUBLIC_INTERFACE
@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="forgot_password",
    summary="Ask for a password reset link",
    description=(
        "Public. Always answers the same way, whether or not the email belongs to a staff "
        "member, so it cannot be used to find out who has an account."
    ),
)
def post_forgot_password(
    payload: ForgotPassword,
    request: Request,
    response: Response,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Queue the lookup and the email; reply identically for every address."""

    if not _link_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    response.headers["Cache-Control"] = "no-store"
    background.add_task(_forgot_in_background, str(payload.email))
    return {"message": "If that email belongs to an account, we have sent a link to reset the password."}


# PUBLIC_INTERFACE
@router.post(
    "/auth/reset",
    response_model=InvitationInfo,
    operation_id="look_up_reset",
    summary="Who a reset link is for",
    responses={404: {"description": "The link has expired or was already used."}},
)
def post_reset_lookup(
    payload: InvitationLookup,
    request: Request,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> InvitationInfo:
    """Check a reset link without using it up."""

    response.headers["Cache-Control"] = "no-store"
    if not _link_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        account = look_up_reset(database, payload.token)
    except WorkflowError as error:
        _error(error)
    return InvitationInfo(
        display_name=account.display_name, email=account.email or "", role_label=ROLE_LABELS[account.role]
    )


# PUBLIC_INTERFACE
@router.post(
    "/auth/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="reset_password",
    summary="Choose a new password from a reset link",
    responses={404: {"description": "The link has expired or was already used."}, 422: {"description": "The password is not acceptable."}},
)
def post_reset_password(
    payload: SetPassword,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    database: Annotated[Session, Depends(get_db)],
) -> Response:
    """Set the new password, end every open session and email a notice."""

    if not _link_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        account = complete_reset(database, secret=payload.token, password=payload.password)
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _error(error)
    background.add_task(_send_changed_notice, account.email or "", account.display_name)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# PUBLIC_INTERFACE
@router.post(
    "/auth/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="change_password",
    summary="Change your own password",
    description="Signed-in people only. Needs the current password. Other browsers are signed out; this one stays signed in.",
    responses={422: {"description": "The current password is wrong or the new one is not acceptable."}},
)
def post_change_password(
    payload: ChangePassword,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    account: Annotated[UserAccount, Depends(get_current_user)],
    database: Annotated[Session, Depends(get_db)],
) -> Response:
    """Change the password and keep this browser signed in with a fresh session."""

    if not _link_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        change_password(
            database, account=account, current=payload.current_password, new=payload.new_password, verify=verify_password
        )
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _error(error)
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(account),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    background.add_task(_send_changed_notice, account.email or "", account.display_name)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# PUBLIC_INTERFACE
@router.post(
    "/api/users/{account_id}/send-reset",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="send_staff_reset",
    summary="Email a person a password reset link",
    description="Administrators only. The link goes to the person, never to the administrator.",
)
def post_send_reset(
    account_id: uuid.UUID,
    actor: Annotated[UserAccount, Depends(require_permissions("*"))],
    database: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    """Send a reset link."""

    target = database.get(UserAccount, account_id)
    if target is None or not target.email:
        raise HTTPException(status_code=404, detail="That account has no email address to send a reset to.")
    made = request_reset(database, email=target.email, actor=actor, force=True)
    database.commit()
    if made is None:
        raise HTTPException(status_code=409, detail="A reset can only be sent to an active account.")
    account, secret = made
    return {"email_sent": _send_reset(account.email or "", account.display_name, secret, True)}
