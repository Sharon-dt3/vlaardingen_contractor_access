"""APIs for QR walk-up registration: arrive, register, confirm the rules, be recorded."""

from __future__ import annotations

import uuid
from io import BytesIO
import logging
from datetime import datetime, timedelta
from typing import Annotated, Union

import qrcode
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import Person, UserAccount
from app.rate_limit import RateLimiter
from app.providers.walk_up_email import (
    WalkUpEmailError,
    send_walk_up_code_email,
    send_walk_up_pass_email,
)
from app.schemas.walk_up import (
    GateAdmitRequest,
    GateExitRequest,
    GateRefuseRequest,
    GateLookupRequest,
    GateWalkUpResponse,
    WalkUpRegistrationCreate,
    WalkUpRegistrationReceipt,
    WalkUpOnSiteRow,
    WalkUpRegistrationRow,
    WalkUpResendRequest,
    WalkUpSiteLinkResponse,
    WalkUpSiteResponse,
    WalkUpVerificationRequired,
    WalkUpVerifyRequest,
)
from app.security import require_permissions
from app.services.walk_up import (
    CODE_VALID_MINUTES,
    RESEND_COOLDOWN_SECONDS,
    admit_at_gate,
    active_sites,
    email_hint,
    list_on_site,
    record_exit,
    refuse_at_gate,
    resend_email_code,
    start_email_check,
    verify_email_code,
    lookup_for_gate,
    pass_qr_data_url,
    pass_qr_png,
    list_registrations,
    reference_for,
    register_walk_up,
    site_for_key,
    site_key,
)
from app.services.workflows import WorkflowError

router = APIRouter(prefix="/api/walk-up", tags=["Walk-up registration"])
_LOGGER = logging.getLogger(__name__)

# Many contractors can share one guest Wi-Fi address, so the limit is generous.
_registration_limiter = RateLimiter(limit=30, window_seconds=600)
_verify_limiter = RateLimiter(limit=60, window_seconds=600)


def email_check_enabled() -> bool:
    """Whether walk-up people must enter an emailed code before they are registered."""

    return get_settings().walk_up_email_check.strip().lower() != "off"


def _email_entry_qr(
    settings: object,
    *,
    to: str,
    first_name: str,
    site_name: str,
    reference: str,
    valid_until: datetime,
    qr_png: bytes,
    valid_from: datetime | None = None,
    timezone_name: str = "UTC",
) -> None:
    """Send the entry QR after the response. A failure never undoes the registration."""

    try:
        send_walk_up_pass_email(
            settings,
            to=to,
            first_name=first_name,
            site_name=site_name,
            reference=reference,
            valid_until=valid_until,
            qr_png=qr_png,
            valid_from=valid_from,
            timezone_name=timezone_name,
        )
        _LOGGER.info("Walk-up entry QR emailed for registration %s.", reference)
    except WalkUpEmailError:
        _LOGGER.warning("Walk-up entry QR email could not be sent for registration %s.", reference)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _raise_api_error(error: WorkflowError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _arrival_url(site_key_value: str) -> str:
    # WEB_ORIGIN is configured server-side; never trust the request Host.
    return f"{get_settings().web_origin.rstrip('/')}/arrive/{site_key_value}"


# PUBLIC_INTERFACE
@router.get(
    "/sites",
    response_model=list[WalkUpSiteLinkResponse],
    operation_id="list_walk_up_sites",
    summary="Sites with the address their QR code opens",
    description="For authorized staff: each active site and the link to print as a QR code.",
)
def get_walk_up_sites(
    _: Annotated[UserAccount, Depends(require_permissions("people:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[WalkUpSiteLinkResponse]:
    """List the sites and their arrival links."""

    return [
        WalkUpSiteLinkResponse(
            site_key=site_key(site), site_name=site.name, arrival_url=_arrival_url(site_key(site))
        )
        for site in active_sites(database)
    ]


# PUBLIC_INTERFACE
@router.get(
    "/sites/{key}",
    response_model=WalkUpSiteResponse,
    operation_id="get_walk_up_site",
    summary="Which site a QR code belongs to",
    description="Public: the arrival page shows the site name before anything is entered.",
    responses={404: {"description": "The QR code does not belong to a site."}},
)
def get_walk_up_site(
    key: str, database: Annotated[Session, Depends(get_db)]
) -> WalkUpSiteResponse:
    """Return the site for a QR link."""

    try:
        site = site_for_key(database, key)
    except WorkflowError as error:
        _raise_api_error(error)
    return WalkUpSiteResponse(site_key=site_key(site), site_name=site.name)


# PUBLIC_INTERFACE
@router.get(
    "/qr.png",
    operation_id="get_walk_up_qr",
    summary="The QR code image for a site",
    description="Public: the image encodes only the site's arrival link, nothing personal.",
    responses={200: {"content": {"image/png": {}}}, 404: {"description": "Unknown site."}},
)
def get_walk_up_qr(
    database: Annotated[Session, Depends(get_db)],
    site: Annotated[str, Query(min_length=1, max_length=80)],
) -> Response:
    """Render the site's arrival link as a printable QR code."""

    try:
        found = site_for_key(database, site)
    except WorkflowError as error:
        _raise_api_error(error)
    image = qrcode.make(
        _arrival_url(site_key(found)), error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10
    )
    output = BytesIO()
    image.save(output, format="PNG")
    return Response(
        content=output.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


# PUBLIC_INTERFACE
@router.post(
    "/registrations",
    response_model=Union[WalkUpRegistrationReceipt, WalkUpVerificationRequired],
    status_code=status.HTTP_201_CREATED,
    operation_id="register_walk_up",
    summary="Register on arrival and confirm the life-saving rules",
    description=(
        "Public, with no invitation: the person scanned the site's QR code. With the email "
        "check on (the default) this returns 202 and emails a six-digit code; nothing is "
        "stored as a person until the code is entered at /registrations/verify. With the "
        "check off it registers at once and returns 201 with the entry QR. Either way the "
        "person's name, company, email, own confirmation (exact wording, version, time) and "
        "arrival are stored together or not at all."
    ),
    responses={
        202: {"model": WalkUpVerificationRequired, "description": "A code was emailed."},
        404: {"description": "Unknown site or rules version."},
        409: {"description": "The rules have been updated since the page was loaded."},
        422: {"description": "A field is invalid or the box was not ticked."},
        429: {"description": "Too many registrations from this address."},
        503: {"description": "The email check is on but the code could not be sent."},
    },
)
def post_walk_up_registration(
    payload: WalkUpRegistrationCreate,
    request: Request,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> Union[WalkUpRegistrationReceipt, WalkUpVerificationRequired]:
    """Record an arrival, or start its email check."""

    response.headers["Cache-Control"] = "no-store"
    if not _registration_limiter.allow(_client_key(request)):
        raise HTTPException(
            status_code=429, detail="Too many registrations from this connection. Try again shortly."
        )
    fields = dict(
        site_key_value=payload.site_key,
        first_name=payload.first_name,
        last_name=payload.last_name,
        company_name=payload.company_name,
        email=str(payload.email),
        population=payload.population,
        rules_version_id=payload.rules_version_id,
        language=payload.language,
        confirmed=payload.confirmed,
    )
    try:
        if email_check_enabled():
            settings = get_settings()
            if settings.notification_provider != "smtp":
                raise HTTPException(
                    status_code=503,
                    detail="The email check is switched on, but no mail server is set up. Ask site staff for help.",
                )
            pending, code, site = start_email_check(database, **fields)
            try:
                send_walk_up_code_email(
                    settings,
                    to=pending.email,
                    code=code,
                    site_name=site.name,
                    valid_minutes=CODE_VALID_MINUTES,
                )
            except WalkUpEmailError as error:
                database.rollback()
                raise HTTPException(
                    status_code=503, detail="The code email could not be sent. Try again in a moment."
                ) from error
            outcome = WalkUpVerificationRequired(
                pending_id=pending.id,
                email_hint=email_hint(pending.email),
                code_expires_at=pending.code_expires_at,
                resend_available_at=pending.last_sent_at + timedelta(seconds=RESEND_COOLDOWN_SECONDS),
            )
            database.commit()
            response.status_code = status.HTTP_202_ACCEPTED
            return outcome

        registration, site, rules, acknowledgement, pass_secret = register_walk_up(database, **fields)
        receipt = WalkUpRegistrationReceipt(
            reference=reference_for(registration.id),
            site_name=site.name,
            registered_at=registration.registered_at,
            rules_version=rules.version,
            language=acknowledgement.language,
            pass_qr=pass_qr_data_url(pass_secret, reference_for(registration.id)),
            pass_valid_from=registration.pass_valid_from,
            pass_valid_until=registration.pass_expires_at,
            site_timezone=site.timezone,
        )
        database.commit()
        return receipt
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except HTTPException:
        raise
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/registrations/verify",
    response_model=WalkUpRegistrationReceipt,
    status_code=status.HTTP_201_CREATED,
    operation_id="verify_walk_up_email",
    summary="Enter the emailed code and finish registering",
    description=(
        "Public. A wrong code counts against a small limit that is saved even though the "
        "request fails. The right code registers the person, stores their confirmation and "
        "returns their entry QR."
    ),
    responses={
        404: {"description": "The registration has expired."},
        410: {"description": "The code has expired."},
        422: {"description": "The code is not right."},
        429: {"description": "Too many wrong codes."},
    },
)
def post_walk_up_verify(
    payload: WalkUpVerifyRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    database: Annotated[Session, Depends(get_db)],
) -> WalkUpRegistrationReceipt:
    """Finish a registration with its email code, then email the entry QR."""

    response.headers["Cache-Control"] = "no-store"
    if not _verify_limiter.allow(_client_key(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    try:
        registration, site, rules, acknowledgement, pass_secret = verify_email_code(
            database, pending_id=payload.pending_id, code=payload.code
        )
        reference = reference_for(registration.id)
        person = database.get(Person, registration.person_id)
        receipt = WalkUpRegistrationReceipt(
            reference=reference,
            site_name=site.name,
            registered_at=registration.registered_at,
            rules_version=rules.version,
            language=acknowledgement.language,
            pass_qr=pass_qr_data_url(pass_secret, reference),
            pass_valid_from=registration.pass_valid_from,
            pass_valid_until=registration.pass_expires_at,
            site_timezone=site.timezone,
            emailed_to=email_hint(person.email),
        )
        email_job = dict(
            to=person.email,
            first_name=person.first_name,
            site_name=site.name,
            reference=reference,
            valid_until=registration.pass_expires_at,
            valid_from=registration.pass_valid_from,
            timezone_name=site.timezone,
            qr_png=pass_qr_png(pass_secret, reference),
        )
        database.commit()
        # The address was just proven with a code. Send the QR after the response is returned.
        background.add_task(_email_entry_qr, get_settings(), **email_job)
        return receipt
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/registrations/resend",
    response_model=WalkUpVerificationRequired,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="resend_walk_up_code",
    summary="Email a new code",
    description="Public. Limited to a few sends per registration and a short wait between them.",
    responses={404: {"description": "The registration has expired."}, 429: {"description": "Too many sends."}},
)
def post_walk_up_resend(
    payload: WalkUpResendRequest,
    request: Request,
    response: Response,
    database: Annotated[Session, Depends(get_db)],
) -> WalkUpVerificationRequired:
    """Send another code."""

    response.headers["Cache-Control"] = "no-store"
    if not _verify_limiter.allow(_client_key(request)):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    settings = get_settings()
    try:
        pending, code, site = resend_email_code(database, pending_id=payload.pending_id)
        try:
            send_walk_up_code_email(
                settings,
                to=pending.email,
                code=code,
                site_name=site.name,
                valid_minutes=CODE_VALID_MINUTES,
            )
        except WalkUpEmailError as error:
            database.rollback()
            raise HTTPException(
                status_code=503, detail="The code email could not be sent. Try again in a moment."
            ) from error
        outcome = WalkUpVerificationRequired(
            pending_id=pending.id,
            email_hint=email_hint(pending.email),
            code_expires_at=pending.code_expires_at,
            resend_available_at=pending.last_sent_at + timedelta(seconds=RESEND_COOLDOWN_SECONDS),
        )
        database.commit()
        return outcome
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except HTTPException:
        raise
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.get(
    "/registrations",
    response_model=list[WalkUpRegistrationRow],
    operation_id="list_walk_up_registrations",
    summary="Who arrived through the QR code",
    description="For authorized staff: recent arrivals with the wording each person confirmed.",
)
def get_walk_up_registrations(
    _: Annotated[UserAccount, Depends(require_permissions("people:read"))],
    database: Annotated[Session, Depends(get_db)],
    since_hours: Annotated[int, Query(ge=1, le=720)] = 24,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    site_id: uuid.UUID | None = None,
) -> list[WalkUpRegistrationRow]:
    """List recent arrivals."""

    return [
        WalkUpRegistrationRow.model_validate(row)
        for row in list_registrations(
            database, since_hours=since_hours, limit=limit, site_id=site_id
        )
    ]


# PUBLIC_INTERFACE
@router.post(
    "/gate/lookup",
    response_model=GateWalkUpResponse,
    operation_id="lookup_walk_up_at_gate",
    summary="Who is this walk-up QR or code, and may they enter",
    description=(
        "For a gate operator: the kiosk sends what it scanned from the person's QR, or the "
        "short reference they read out. Shows name, company, when they registered and whether "
        "they confirmed the life-saving rules, and whether the records allow entry. Changes "
        "nothing about the person, but every check is written to the audit trail: a lookup, a "
        "refusal (the records do not allow entry), or a code that matches no recent registration."
    ),
    responses={404: {"description": "No recent registration matches."}},
)
def post_walk_up_gate_lookup(
    payload: GateLookupRequest,
    actor: Annotated[UserAccount, Depends(require_permissions("gate:evaluate"))],
    database: Annotated[Session, Depends(get_db)],
    response: Response,
) -> GateWalkUpResponse:
    """Look up an arrival at the kiosk."""

    response.headers["Cache-Control"] = "no-store"
    try:
        result = GateWalkUpResponse.model_validate(
            lookup_for_gate(database, actor=actor, site_key_value=payload.site_key, code=payload.code)
        )
        database.commit()
        return result
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/gate/admit",
    response_model=GateWalkUpResponse,
    operation_id="admit_walk_up_at_gate",
    summary="Let a walk-up registrant in",
    description=(
        "For a gate operator. The server re-checks the records and refuses if the person "
        "has not confirmed the current rules, is not allowed on site or is blacklisted. "
        "The entry, the operator and the time are stored and audited. Repeating it changes nothing."
    ),
    responses={404: {"description": "No recent registration."}, 409: {"description": "Entry is not allowed."}},
)
def post_walk_up_gate_admit(
    payload: GateAdmitRequest,
    actor: Annotated[UserAccount, Depends(require_permissions("gate:evaluate"))],
    database: Annotated[Session, Depends(get_db)],
    response: Response,
) -> GateWalkUpResponse:
    """Record the operator's entry decision."""

    response.headers["Cache-Control"] = "no-store"
    try:
        result = admit_at_gate(
            database,
            actor=actor,
            site_key_value=payload.site_key,
            registration_id=payload.registration_id,
        )
        database.commit()
        return GateWalkUpResponse.model_validate(result)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.post(
    "/gate/exit",
    response_model=GateWalkUpResponse,
    operation_id="record_walk_up_exit",
    summary="Record that a walk-up person has left",
    description=(
        "For a gate operator. Only someone who was let in can leave. The exit, the operator "
        "and the time are stored and audited. Repeating it changes nothing."
    ),
    responses={404: {"description": "No such registration."}, 409: {"description": "They were never let in."}},
)
def post_walk_up_gate_exit(
    payload: GateExitRequest,
    actor: Annotated[UserAccount, Depends(require_permissions("presence:write"))],
    database: Annotated[Session, Depends(get_db)],
    response: Response,
) -> GateWalkUpResponse:
    """Record an exit."""

    response.headers["Cache-Control"] = "no-store"
    try:
        result = record_exit(
            database,
            actor=actor,
            site_key_value=payload.site_key,
            registration_id=payload.registration_id,
        )
        database.commit()
        return GateWalkUpResponse.model_validate(result)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise


# PUBLIC_INTERFACE
@router.get(
    "/on-site",
    response_model=list[WalkUpOnSiteRow],
    operation_id="list_walk_up_on_site",
    summary="Walk-up people on site now",
    description="For authorized staff: everyone let in through the walk-up path who has not left.",
)
def get_walk_up_on_site(
    _: Annotated[UserAccount, Depends(require_permissions("presence:read"))],
    database: Annotated[Session, Depends(get_db)],
    site_id: uuid.UUID | None = None,
) -> list[WalkUpOnSiteRow]:
    """List who is on site."""

    return [WalkUpOnSiteRow.model_validate(row) for row in list_on_site(database, site_id=site_id)]


# PUBLIC_INTERFACE
@router.post(
    "/gate/refuse",
    response_model=GateWalkUpResponse,
    operation_id="refuse_walk_up_at_gate",
    summary="Record that the officer turned a walk-up person away",
    description=(
        "For a gate operator. Used when the officer refuses someone the records would allow "
        "in, for example because the person does not match their ID. The reason, an optional "
        "note and the operator are written to the audit trail. It does not block a later entry."
    ),
    responses={
        404: {"description": "No such registration."},
        409: {"description": "They were already let in."},
        422: {"description": "A reason is required."},
    },
)
def post_walk_up_gate_refuse(
    payload: GateRefuseRequest,
    actor: Annotated[UserAccount, Depends(require_permissions("gate:evaluate"))],
    database: Annotated[Session, Depends(get_db)],
    response: Response,
) -> GateWalkUpResponse:
    """Record a refusal."""

    response.headers["Cache-Control"] = "no-store"
    try:
        result = refuse_at_gate(
            database,
            actor=actor,
            site_key_value=payload.site_key,
            registration_id=payload.registration_id,
            reason=payload.reason,
            note=payload.note,
        )
        database.commit()
        return GateWalkUpResponse.model_validate(result)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    except Exception:
        database.rollback()
        raise
