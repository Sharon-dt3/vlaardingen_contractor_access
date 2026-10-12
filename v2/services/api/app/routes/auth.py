"""Authentication routes for deterministic local demo accounts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import UserAccount
from app.schemas.auth import LoginRequest, SessionResponse, UserResponse
from app.rate_limit import RateLimiter
from app.services.accounts import check_sign_in
from app.services.audit import append_audit_event
from app.security import (
    create_session_token,
    get_current_user,
    permissions_for_role,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
_login_limiter = RateLimiter(limit=40, window_seconds=600)


def _user_response(account: UserAccount) -> UserResponse:
    return UserResponse(
        id=str(account.id),
        handle=account.handle,
        display_name=account.display_name,
        role=account.role,
        permissions=permissions_for_role(account.role),
    )


# PUBLIC_INTERFACE
@router.post(
    "/login",
    response_model=SessionResponse,
    operation_id="login",
    summary="Sign in with a seeded demo account",
    description=(
        "Validates the configured local demo password and sets a short-lived, "
        "HMAC-signed HttpOnly SameSite cookie."
    ),
    responses={
        401: {"description": "The handle or password is invalid."},
        422: {"description": "The submitted credentials are malformed."},
    },
)
def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> SessionResponse:
    """Authenticate by email (or the demo handle) and return the role and permissions.

    Five wrong passwords lock the account for fifteen minutes. The reply never says whether
    the account exists, is locked or is deactivated, so it cannot be used to find staff emails.
    Every success, failure and lockout is written to the audit trail.
    """

    if not _login_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts from this connection. Try again in a few minutes.",
        )
    handle = credentials.handle.strip().lower()
    account, outcome = check_sign_in(
        database, handle=handle, password=credentials.password, verify=verify_password
    )
    if account is None:
        known = database.scalar(select(UserAccount).where(UserAccount.handle == handle))
        append_audit_event(
            database,
            actor=None,
            action="auth.locked" if outcome == "locked_now" else "auth.login_failed",
            entity_type="user_account",
            entity_id=str(known.id) if known else "unknown",
            reason="A sign-in was refused." if outcome != "locked_now" else "The account was locked after repeated wrong passwords.",
            details={"handle": handle[:64], "reason": outcome},
        )
        database.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password, or the account is temporarily locked. Try again later.",
        )
    append_audit_event(
        database,
        actor=account,
        action="auth.login",
        entity_type="user_account",
        entity_id=str(account.id),
        reason="The person signed in.",
        details={"handle": account.handle},
    )
    database.commit()

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
    return SessionResponse(
        user=_user_response(account),
        expires_in_seconds=settings.session_ttl_seconds,
    )


# PUBLIC_INTERFACE
@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="logout",
    summary="Sign out the current browser session",
    description="Expires the local signed session cookie.",
    responses={204: {"description": "The browser session was cleared."}},
)
def logout(response: Response) -> Response:
    """Clear the signed session cookie and return no response body.

    Args:
        response: FastAPI response used to expire the cookie.

    Returns:
        The empty response with the session cookie expired.
    """

    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# PUBLIC_INTERFACE
@router.get(
    "/me",
    response_model=UserResponse,
    operation_id="get_current_user",
    summary="Get the current demo user",
    description="Returns role and permission data from the verified signed session.",
    responses={
        401: {"description": "No current valid session exists."},
    },
)
def current_user(
    account: Annotated[UserAccount, Depends(get_current_user)],
) -> UserResponse:
    """Return the account represented by the current signed cookie.

    Args:
        account: Active account resolved by the authentication dependency.

    Returns:
        Current user details and effective permissions.
    """

    return _user_response(account)
