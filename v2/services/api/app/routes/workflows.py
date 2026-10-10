"""Authorized APIs for invitation, registration, and private evidence workflows."""

from __future__ import annotations

import json
import uuid
from html import escape
from typing import Annotated
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import get_db
from app.models import Evidence, EvidenceStatus, Invitation, Person, Site, UserAccount
from app.providers.invitation_email import InvitationEmailError, send_invitation_email
from app.providers import (
    DocumentExtractionProvider,
    StorageProvider,
    get_document_extraction_provider,
    get_storage_provider,
)
from app.schemas.workflows import (
    EvidenceAssetResponse,
    EvidenceFieldsUpdate,
    EvidenceResponse,
    GateEvidenceExtractionRequest,
    GateIdentityScanResponse,
    EvidenceReviewCommand,
    InvitationCreate,
    InvitationResponse,
    InviteeRegistrationCreate,
    InviteeRegistrationStatus,
    RegistrationCreate,
    RegistrationResponse,
    SyntheticEvidenceAttach,
)
from app.security import require_permissions
from app.services import (
    WorkflowError,
    attach_synthetic_asset,
    create_invitation,
    extract_gate_identity_evidence,
    extract_evidence,
    get_visible_invitation,
    list_assets,
    list_person_evidence,
    match_gate_identity_document,
    list_visible_invitations,
    read_evidence_content,
    register_invitation,
    review_evidence,
    update_evidence_fields,
    upload_gate_identity_evidence,
    upload_evidence,
    upload_invitation_identity_document,
)
from app.services.life_saving import invitee_confirmation
from app.services.workflows import (
    ALLOWED_UPLOADS,
    MAX_UPLOAD_BYTES,
    get_invitee_registration,
    inspect_invitation_response,
    issue_invitation_response_token,
    register_accepted_invitee,
    record_invitation_response,
)
from pathlib import PurePath

router = APIRouter(prefix="/api", tags=["Invitations and evidence"])


def _raise_api_error(error: WorkflowError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _commit_evidence(database: Session, evidence: Evidence) -> Evidence:
    database.commit()
    database.refresh(evidence)
    return evidence


def _invitation_response(
    database: Session, invitation: Invitation
) -> InvitationResponse:
    """Include the linked person's name in an already-authorized invitation."""

    person = (
        database.get(Person, invitation.person_id)
        if invitation.person_id is not None
        else None
    )
    return InvitationResponse.model_validate(
        invitation
    ).model_copy(
        update={
            "registered_name": (
                f"{person.first_name} {person.last_name}" if person else None
            )
        },
    )


def _invitation_responses(
    database: Session, invitations: list[Invitation]
) -> list[InvitationResponse]:
    """Fetch names together for invitations already filtered to the actor's scope."""

    person_ids = {
        invitation.person_id
        for invitation in invitations
        if invitation.person_id is not None
    }
    people = (
        {
            person.id: person
            for person in database.scalars(
                select(Person).where(Person.id.in_(person_ids))
            )
        }
        if person_ids
        else {}
    )
    responses = []
    for invitation in invitations:
        person = people.get(invitation.person_id)
        responses.append(
            InvitationResponse.model_validate(
                invitation
            ).model_copy(
                update={
                    "registered_name": (
                        f"{person.first_name} {person.last_name}" if person else None
                    )
                },
            )
        )
    return responses


# PUBLIC_INTERFACE
@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_invitation",
    summary="Create a site-access invitation",
    description="Creates an invitation and reports SMTP handoff or local-only delivery.",
    responses={
        401: {"description": "Authentication is required."},
        403: {"description": "The account cannot create invitations."},
        404: {"description": "The selected active site does not exist."},
        422: {"description": "The invitation payload is invalid."},
    },
)
def post_invitation(
    payload: InvitationCreate,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("invitations:write")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> Invitation:
    """Create an invitation and attempt delivery to its exact email address.

    Args:
        payload: Recipient, site, and planned visit details.
        actor: Authorized invitation sender.
        database: Request-scoped database session.
    Returns:
        Invitation with delivery status but without bearer-link secrets.
    """

    try:
        invitation = create_invitation(database, actor=actor, payload=payload)
        database.commit()
        settings = get_settings()
        settings.prepare_local_runtime()
        if settings.notification_provider == "smtp":
            token = issue_invitation_response_token(database, invitation)
            database.commit()
            # WEB_ORIGIN is configured server-side; never trust the request Host.
            base = f"{settings.web_origin.rstrip('/')}/api/invitations/respond"
            try:
                send_invitation_email(
                    settings,
                    invitation,
                    database.get(Site, invitation.site_id),
                    f"{base}?token={quote(token)}&decision=accept",
                    f"{base}?token={quote(token)}&decision=decline",
                )
            except InvitationEmailError:
                invitation.delivery_status = "smtp_failed"
            else:
                invitation.delivery_status = "smtp_sent"
            database.commit()
        database.refresh(invitation)
        return _invitation_response(database, invitation)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.get(
    "/invitations/respond",
    operation_id="preview_invitation_email_response",
    summary="Preview an invitation email response",
    description="Show a confirmation form without recording a decision.",
    responses={
        404: {"description": "The link is invalid."},
        409: {"description": "The invitation was already answered."},
        410: {"description": "The link has expired."},
    },
)
def get_invitation_response(
    token: str,
    decision: str,
    database: Annotated[Session, Depends(get_db)],
) -> Response:
    """Preview a recipient's link without consuming its single-use token.

    Args:
        token: Secret carried by the invitation email link.
        decision: Requested accept or decline action.
        database: Request-scoped database session.
    Returns:
        A no-store HTML confirmation page or a safe link-state message.
    """

    try:
        invitation, state = inspect_invitation_response(
            database, token=token, decision=decision
        )
    except WorkflowError as error:
        _raise_api_error(error)

    headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    if state != "pending":
        message = (
            "This invitation has already been answered."
            if state == "already_responded"
            else "This invitation link has expired."
        )
        return Response(
            f"<h1>{message}</h1>",
            status_code=409 if state == "already_responded" else 410,
            media_type="text/html",
            headers=headers,
        )

    label = "Accept Invitation" if decision == "accept" else "Decline Invitation"
    content = (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='referrer' content='no-referrer'>"
        "<title>Confirm invitation response</title><main>"
        f"<h1>{label}</h1>"
        f"<p>Invitation for {escape(invitation.company_name)}. "
        "Confirm your choice below. This does not grant site access.</p>"
        "<form method='post' action='/api/invitations/respond'>"
        f"<input type='hidden' name='token' value='{escape(token, quote=True)}'>"
        f"<input type='hidden' name='decision' value='{escape(decision, quote=True)}'>"
        f"<button type='submit'>{label}</button></form></main></html>"
    )
    return Response(content, media_type="text/html", headers=headers)


# PUBLIC_INTERFACE
@router.post(
    "/invitations/respond",
    operation_id="submit_invitation_email_response",
    summary="Record a single-use invitation response",
    description="Atomically records the recipient's Accept or Decline choice.",
    responses={
        404: {"description": "The link is invalid."},
        409: {"description": "The invitation was already answered."},
        410: {"description": "The link has expired."},
    },
)
def post_invitation_response(
    token: Annotated[str, Form(description="Single-use secret from the email.")],
    decision: Annotated[str, Form(description="Accept or decline.")],
    database: Annotated[Session, Depends(get_db)],
) -> Response:
    """Consume an email response link and show the recorded choice.

    Args:
        token: Single-use secret from the invitation email.
        decision: Either accept or decline.
        database: Request-scoped database session.
    Returns:
        No-store HTML confirmation without the token or private record data.
    """

    try:
        invitation, registration_token = record_invitation_response(
            database, token=token, decision=decision
        )
        database.commit()
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    headers = {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    }
    if registration_token is not None:
        # 303 ensures a refresh cannot repeat the single-use Accept POST.
        return Response(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={
                **headers,
                "Location": f"/register?token={quote(registration_token, safe='')}",
            },
        )
    return Response(
        "<h1>Invitation declined.</h1><p>Your response has been recorded.</p>",
        media_type="text/html",
        headers=headers,
    )


# PUBLIC_INTERFACE
@router.get(
    "/invitations/registration",
    response_model=InviteeRegistrationStatus,
    operation_id="inspect_accepted_invitee_registration",
    summary="Inspect accepted invitee registration",
    description="The separate email registration capability is valid only after acceptance.",
    responses={
        404: {"description": "Invalid or unaccepted registration link."},
        410: {"description": "Registration link expired."},
    },
)
def get_recipient_registration(
    token: str,
    database: Annotated[Session, Depends(get_db)],
    response: Response,
) -> InviteeRegistrationStatus:
    """Return minimal form context for an accepted recipient capability.

    Args:
        token: Private registration capability issued after acceptance.
        database: Request-scoped database session.
        response: HTTP response on which no-store headers are applied.
    Returns:
        Company, population, and completion status without private identifiers.
    """

    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        invitation = get_invitee_registration(database, token=token)
        confirmed, confirmed_at = invitee_confirmation(database, invitation)
        return InviteeRegistrationStatus(
            company_name=invitation.company_name,
            population=invitation.population,
            registration_completed=invitation.registration_completed_at is not None,
            evidence_uploaded=invitation.registration_completed_at is not None,
            life_saving_rules_confirmed=confirmed,
            life_saving_rules_confirmed_at=confirmed_at,
        )
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/invitations/registration",
    response_model=InviteeRegistrationStatus,
    operation_id="submit_accepted_invitee_registration",
    summary="Submit accepted invitee registration and required document",
    description=(
        "Requires a live post-acceptance email capability and a matching ID card "
        "or driving licence. Creates a planned visit and unverified private evidence; "
        "only an administrator can review evidence or authorize later access."
    ),
    responses={
        404: {"description": "Invalid or unaccepted registration link."},
        409: {"description": "Registration has already been submitted."},
        410: {"description": "Registration link or visit window expired."},
        413: {"description": "Document exceeds 5 MiB."},
        415: {"description": "Unsupported document format."},
        422: {"description": "Invalid name, ID expiry date, or identity-document type."},
        503: {"description": "Real document processing is not configured."},
    },
)
async def post_recipient_registration(
    token: Annotated[str, Form(description="Post-acceptance registration capability.")],
    first_name: Annotated[str, Form(description="Name on the identity document.")],
    last_name: Annotated[str, Form(description="Surname on the identity document.")],
    expiry_date: Annotated[str, Form(description="ID expiry date in YYYY-MM-DD format; not yet verified.")],
    evidence_type: Annotated[str, Form(description="ID card or driving licence.")],
    file: Annotated[UploadFile, File(description="Required private identity document.")],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
    parser: Annotated[
        DocumentExtractionProvider, Depends(get_document_extraction_provider)
    ],
    response: Response,
) -> InviteeRegistrationStatus:
    """Register an accepted recipient and privately store required evidence.

    Args:
        token: Capability issued only by a successful Accept POST.
        first_name: Recipient's given name.
        last_name: Recipient's surname.
        expiry_date: Invitee-entered ID expiry date, subject to human review.
        evidence_type: Population-appropriate document category.
        file: Identity document, at most 5 MiB.
        database: Transactional database session.
        storage: Private evidence storage provider.
        parser: Provider configuration determining whether real IDs are allowed.
        response: HTTP response for no-store headers.
    Returns:
        Minimal recipient confirmation, never an approval or access token.
    """

    from pydantic import ValidationError
    from app.models import EvidenceType

    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        payload = InviteeRegistrationCreate(
            first_name=first_name, last_name=last_name, expiry_date=expiry_date
        )
        selected_type = EvidenceType(evidence_type)
        if selected_type not in {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}:
            raise ValueError("Unsupported identity-document type.")
    except (ValidationError, ValueError) as error:
        raise HTTPException(
            status_code=422,
            detail="Enter a valid name, current ID expiry date, and identity-document type.",
        ) from error
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        invitation = register_accepted_invitee(
            database,
            token=token,
            payload=payload,
            evidence_type=selected_type,
            filename=file.filename or "",
            media_type=file.content_type or "application/octet-stream",
            content=content,
            storage=storage,
            allow_real_identity_document=getattr(
                parser, "reads_real_documents", False
            ),
        )
        database.commit()
        return InviteeRegistrationStatus(
            company_name=invitation.company_name,
            population=invitation.population,
            registration_completed=True,
            evidence_uploaded=True,
        )
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    finally:
        await file.close()


# PUBLIC_INTERFACE
@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    operation_id="list_invitations",
    summary="List visible invitations",
    description="Returns only invitations in the authenticated account's scope.",
)
def get_invitations(
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("invitations:read")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> list[InvitationResponse]:
    """List invitations subject to role and object ownership."""

    invitations = list_visible_invitations(database, actor=actor)
    return _invitation_responses(database, invitations)


# PUBLIC_INTERFACE
@router.get(
    "/invitations/{invitation_id}",
    response_model=InvitationResponse,
    operation_id="get_invitation",
    summary="Get one visible invitation",
    description="Returns workflow and linked-record state after object authorization.",
)
def get_invitation(
    invitation_id: uuid.UUID,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("invitations:read")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> InvitationResponse:
    """Return one authorized invitation."""

    try:
        invitation = get_visible_invitation(
            database,
            actor=actor,
            invitation_id=invitation_id,
        )
        return _invitation_response(database, invitation)
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/invitations/{invitation_id}/registration",
    response_model=RegistrationResponse,
    operation_id="register_invitation",
    summary="Create or link invitation registration",
    description=(
        "Matches or creates a fictional company. Without an explicit person ID, "
        "reuses a person only when company, name, and email all match; otherwise "
        "creates a separate person and one planned visit, then advances the "
        "invitation to PRE_REGISTERED."
    ),
    responses={
        403: {"description": "The account cannot register this invitation."},
        404: {"description": "A selected record does not exist."},
        409: {"description": "Duplicate data conflicts with existing ownership."},
    },
)
def post_registration(
    invitation_id: uuid.UUID,
    payload: RegistrationCreate,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("invitations:register")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> RegistrationResponse:
    """Create or link registration records and return their stable identifiers."""

    try:
        (
            invitation,
            company,
            person,
            visit,
            company_created,
            person_created,
        ) = register_invitation(
            database,
            actor=actor,
            invitation_id=invitation_id,
            payload=payload,
        )
        database.commit()
        database.refresh(invitation)
        return RegistrationResponse(
            invitation=_invitation_response(database, invitation),
            company_id=company.id,
            person_id=person.id,
            visit_id=visit.id,
            company_created=company_created,
            person_created=person_created,
        )
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.get(
    "/evidence/assets",
    response_model=list[EvidenceAssetResponse],
    operation_id="list_synthetic_evidence_assets",
    summary="List private synthetic evidence choices",
    description="Returns safe asset metadata and expected mock-extraction fields.",
)
def get_evidence_assets(
    _: Annotated[UserAccount, Depends(require_permissions("evidence:read"))],
    database: Annotated[Session, Depends(get_db)],
) -> list[EvidenceAssetResponse]:
    """List active fictional evidence assets without storage references."""

    return [
        EvidenceAssetResponse.model_validate(asset)
        for asset in list_assets(database)
    ]


# PUBLIC_INTERFACE
@router.post(
    "/invitations/{invitation_id}/evidence/assets",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="attach_synthetic_evidence_asset",
    summary="Attach a seeded synthetic asset",
    description="Creates private evidence metadata from a deterministic asset.",
)
def post_synthetic_evidence(
    invitation_id: uuid.UUID,
    payload: SyntheticEvidenceAttach,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:write")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> Evidence:
    """Attach a private seeded asset to a registered invitation."""

    try:
        evidence = attach_synthetic_asset(
            database,
            actor=actor,
            invitation_id=invitation_id,
            asset_id=payload.asset_id,
        )
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/invitations/{invitation_id}/evidence/uploads",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_private_evidence",
    summary="Upload private invitation evidence",
    description=(
        "Accepts any file format up to 5 MiB and stores bytes outside the public "
        "web application. Formats unsupported by the configured extraction path "
        "remain uploaded without extracted fields or a validity claim."
    ),
    responses={
        413: {"description": "The upload exceeds the 5 MiB limit."},
        422: {"description": "The file is empty, unsafe, or eligible for extraction but not visibly synthetic."},
    },
)
async def post_evidence_upload(
    invitation_id: uuid.UUID,
    evidence_type: Annotated[
        str,
        Form(description="Evidence type enum value."),
    ],
    file: Annotated[UploadFile, File(description="Visibly synthetic document.")],
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:write")),
    ],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
    parser: Annotated[
        DocumentExtractionProvider,
        Depends(get_document_extraction_provider),
    ],
) -> Evidence:
    """Store an authorized invitation upload and extract only supported formats.

    Args:
        invitation_id: Invitation receiving the evidence.
        evidence_type: Selected evidence category.
        file: Uploaded file, limited to 5 MiB.
        actor: Account authorized to upload evidence.
        database: Request-scoped database session.
        storage: Private evidence storage provider.
        parser: Configured extraction provider for supported formats.
    Returns:
        Private evidence metadata; unsupported formats remain unextracted.
    """

    from app.models import EvidenceType

    try:
        selected_type = EvidenceType(evidence_type)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported evidence type.",
        ) from error

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        evidence = upload_evidence(
            database,
            actor=actor,
            invitation_id=invitation_id,
            evidence_type=selected_type,
            filename=file.filename or "",
            media_type=file.content_type or "application/octet-stream",
            content=content,
            storage=storage,
            allow_real_identity_document=getattr(
                parser, "reads_real_documents", False
            ),
        )
        # Do not invoke either the mock or external parser on an opaque format:
        # the mock can otherwise report fictional extracted fields as real work.
        suffix = PurePath(evidence.filename).suffix.lower()
        if (
            suffix in ALLOWED_UPLOADS
            and evidence.media_type in ALLOWED_UPLOADS[suffix]
        ):
            try:
                evidence = extract_evidence(
                    database,
                    actor=actor,
                    evidence_id=evidence.id,
                    parser=parser,
                )
            except WorkflowError as error:
                if error.status_code != 503:
                    raise
                # Provider outages must not discard a valid private upload.
                # Keep it UPLOADED for a later explicit extraction attempt.
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    finally:
        await file.close()


# PUBLIC_INTERFACE
@router.post(
    "/invitations/{invitation_id}/identity-document",
    response_model=InvitationResponse,
    operation_id="upload_invitation_identity_document",
    summary="Upload the private ID associated with an invitation",
    description=(
        "Stores a private ID and its server-calculated digest for later "
        "deterministic gate matching. This endpoint performs no extraction "
        "and does not use an external document provider."
    ),
    responses={
        403: {"description": "The account cannot update this invitation."},
        404: {"description": "The invitation does not exist."},
        413: {"description": "The upload exceeds the 5 MiB limit."},
        415: {"description": "The extension or MIME type is not allowed."},
        422: {"description": "The file is empty or unsafe."},
    },
)
async def post_invitation_identity_document(
    invitation_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="Private invitation ID document.")],
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:write")),
    ],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
) -> Invitation:
    """Privately upload an invitation ID for exact server-side gate matching."""

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        invitation = upload_invitation_identity_document(
            database,
            actor=actor,
            invitation_id=invitation_id,
            filename=file.filename or "",
            media_type=file.content_type or "application/octet-stream",
            content=content,
            storage=storage,
        )
        database.commit()
        database.refresh(invitation)
        return invitation
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    finally:
        await file.close()


# PUBLIC_INTERFACE
@router.post(
    "/gate/identity-scans",
    response_model=GateIdentityScanResponse,
    operation_id="match_gate_identity_document",
    summary="Match a scanned ID to the invitation ID",
    description=(
        "Resolves the invitation only from the scanned opaque token and "
        "compares the gate-scanned ID to the private ID uploaded with that "
        "invitation. The matching decision is server-authoritative and does "
        "not invoke document extraction or Anthropic."
    ),
    responses={
        403: {"description": "The account cannot operate the gate."},
        404: {"description": "The scanned token cannot be matched."},
        409: {"description": "The token has no registered invitation workflow."},
        413: {"description": "The upload exceeds the 5 MiB limit."},
        415: {"description": "The extension or MIME type is not allowed."},
        422: {"description": "The scan file is empty or unsafe."},
    },
)
async def post_gate_identity_scan(
    token_reference: Annotated[
        str,
        Form(description="Scanned opaque access-token reference."),
    ],
    file: Annotated[UploadFile, File(description="Private gate-scanned ID file.")],
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("gate:evaluate")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> GateIdentityScanResponse:
    """Compare one gate-scanned ID file against its token-bound invitation ID."""

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        result = match_gate_identity_document(
            database,
            actor=actor,
            token_reference=token_reference,
            filename=file.filename or "",
            media_type=file.content_type or "application/octet-stream",
            content=content,
        )
        database.commit()
        return GateIdentityScanResponse.model_validate(result)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    finally:
        await file.close()


# PUBLIC_INTERFACE
@router.post(
    "/gate/evidence/uploads",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_gate_identity_evidence",
    summary="Privately upload ID evidence for a scanned gate token",
    description=(
        "Binds a Netherlands ID card or driving licence to the registered "
        "invitation resolved exclusively from the scanned opaque token. The "
        "API stores the file privately; the browser receives no storage path "
        "or extraction-provider credentials."
    ),
    responses={
        403: {"description": "The account cannot operate the gate."},
        404: {"description": "The scanned token cannot be matched."},
        409: {"description": "The token has no registered evidence workflow."},
        413: {"description": "The upload exceeds the 5 MiB limit."},
        415: {"description": "The extension or MIME type is not allowed."},
        422: {"description": "The file or selected identity-document type is invalid."},
        503: {"description": "Real identity-document extraction is not configured."},
    },
)
async def post_gate_evidence_upload(
    token_reference: Annotated[
        str,
        Form(description="Scanned opaque access-token reference."),
    ],
    evidence_type: Annotated[
        str,
        Form(description="ID card or driving-licence evidence type."),
    ],
    file: Annotated[UploadFile, File(description="Private Dutch identity document.")],
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("gate:evaluate")),
    ],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
    parser: Annotated[
        DocumentExtractionProvider,
        Depends(get_document_extraction_provider),
    ],
) -> Evidence:
    """Store one authorized gate-presented identity document without reviewing it."""

    from app.models import EvidenceType

    try:
        selected_type = EvidenceType(evidence_type)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported identity-document type.",
        ) from error

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        evidence = upload_gate_identity_evidence(
            database,
            actor=actor,
            token_reference=token_reference,
            evidence_type=selected_type,
            filename=file.filename or "",
            media_type=file.content_type or "application/octet-stream",
            content=content,
            storage=storage,
            allow_real_identity_document=getattr(
                parser, "reads_real_documents", False
            ),
        )
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)
    finally:
        await file.close()


# PUBLIC_INTERFACE
@router.post(
    "/gate/evidence/{evidence_id}/extract",
    response_model=EvidenceResponse,
    operation_id="extract_gate_identity_evidence",
    summary="Extract fields from a gate-presented identity document",
    description=(
        "Runs the configured server-side extraction provider only after "
        "confirming that the evidence belongs to the supplied scanned token. "
        "Extraction does not verify the document or grant site access."
    ),
    responses={
        403: {"description": "The account cannot operate the gate."},
        404: {"description": "The token or its matching gate evidence was not found."},
        409: {"description": "The evidence cannot be extracted in its current state."},
        503: {"description": "The configured extraction provider is unavailable."},
    },
)
def post_gate_evidence_extraction(
    evidence_id: uuid.UUID,
    payload: GateEvidenceExtractionRequest,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("gate:evaluate")),
    ],
    database: Annotated[Session, Depends(get_db)],
    parser: Annotated[
        DocumentExtractionProvider,
        Depends(get_document_extraction_provider),
    ],
) -> Evidence:
    """Extract server-side fields for a token-bound gate identity-document upload."""

    try:
        evidence = extract_gate_identity_evidence(
            database,
            actor=actor,
            token_reference=payload.token_reference,
            evidence_id=evidence_id,
            parser=parser,
        )
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.get(
    "/people/{person_id}/evidence",
    response_model=list[EvidenceResponse],
    operation_id="list_person_evidence",
    summary="List authorized person evidence",
    description="Returns evidence metadata and expiry fields without storage paths.",
)
def get_person_evidence(
    person_id: uuid.UUID,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:read")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> list[Evidence]:
    """List evidence visible to compliance roles or the owning participant."""

    try:
        return list_person_evidence(database, actor=actor, person_id=person_id)
    except WorkflowError as error:
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/evidence/{evidence_id}/extract",
    response_model=EvidenceResponse,
    operation_id="extract_evidence",
    summary="Extract private document fields",
    description=(
        "Runs the configured server-side extraction provider. Returned fields "
        "remain editable and require authorized human verification before they "
        "can satisfy a gate-relevant evidence requirement."
    ),
)
def post_evidence_extraction(
    evidence_id: uuid.UUID,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:write")),
    ],
    database: Annotated[Session, Depends(get_db)],
    parser: Annotated[
        DocumentExtractionProvider,
        Depends(get_document_extraction_provider),
    ],
) -> Evidence:
    """Extract fields from authorized private evidence without verifying it."""

    try:
        evidence = extract_evidence(
            database,
            actor=actor,
            evidence_id=evidence_id,
            parser=parser,
        )
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.patch(
    "/evidence/{evidence_id}/fields",
    response_model=EvidenceResponse,
    operation_id="edit_evidence_fields",
    summary="Edit extracted evidence fields",
    description="Allows a compliance reviewer to correct fields and validity dates.",
)
def patch_evidence_fields(
    evidence_id: uuid.UUID,
    payload: EvidenceFieldsUpdate,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:review")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> Evidence:
    """Persist reviewer corrections for extracted fields."""

    try:
        evidence = update_evidence_fields(
            database,
            actor=actor,
            evidence_id=evidence_id,
            payload=payload,
        )
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


def _review(
    database: Session,
    actor: UserAccount,
    evidence_id: uuid.UUID,
    payload: EvidenceReviewCommand,
    target: EvidenceStatus,
) -> Evidence:
    try:
        evidence = review_evidence(
            database,
            actor=actor,
            evidence_id=evidence_id,
            target_status=target,
            reason=payload.reason,
        )
        return _commit_evidence(database, evidence)
    except WorkflowError as error:
        database.rollback()
        _raise_api_error(error)


# PUBLIC_INTERFACE
@router.post(
    "/evidence/{evidence_id}/verify",
    response_model=EvidenceResponse,
    operation_id="verify_evidence",
    summary="Manually verify reviewed evidence",
    description="An authorized reviewer explicitly verifies uploaded or extracted evidence after inspecting the private document; advances its invitation.",
)
def post_evidence_verification(
    evidence_id: uuid.UUID,
    payload: EvidenceReviewCommand,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:review")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> Evidence:
    """Record an authorized manual verification, preserving any validity metadata."""

    return _review(
        database,
        actor,
        evidence_id,
        payload,
        EvidenceStatus.VERIFIED,
    )


# PUBLIC_INTERFACE
@router.post(
    "/evidence/{evidence_id}/reject",
    response_model=EvidenceResponse,
    operation_id="reject_evidence",
    summary="Reject evidence",
    description="Records a reviewer rejection without deleting evidence history.",
)
def post_evidence_rejection(
    evidence_id: uuid.UUID,
    payload: EvidenceReviewCommand,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:review")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> Evidence:
    """Reject evidence with an append-only audit reason."""

    return _review(
        database,
        actor,
        evidence_id,
        payload,
        EvidenceStatus.REJECTED,
    )


# PUBLIC_INTERFACE
@router.post(
    "/evidence/{evidence_id}/request-reupload",
    response_model=EvidenceResponse,
    operation_id="request_evidence_reupload",
    summary="Request replacement evidence",
    description="Retains the current record and allows a later upload to supersede it.",
)
def post_evidence_reupload_request(
    evidence_id: uuid.UUID,
    payload: EvidenceReviewCommand,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:review")),
    ],
    database: Annotated[Session, Depends(get_db)],
) -> Evidence:
    """Request replacement evidence while retaining prior history."""

    return _review(
        database,
        actor,
        evidence_id,
        payload,
        EvidenceStatus.REUPLOAD_REQUESTED,
    )


# PUBLIC_INTERFACE
@router.get(
    "/evidence/{evidence_id}/content",
    operation_id="download_private_evidence",
    summary="Retrieve authorized private evidence",
    description="Streams bytes only after permission and object-scope checks.",
    responses={404: {"description": "Evidence or private content is unavailable."}},
)
def get_evidence_content(
    evidence_id: uuid.UUID,
    actor: Annotated[
        UserAccount,
        Depends(require_permissions("evidence:read")),
    ],
    database: Annotated[Session, Depends(get_db)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
) -> Response:
    """Return authorized private evidence bytes without exposing storage paths."""

    try:
        evidence, content = read_evidence_content(
            database,
            actor=actor,
            evidence_id=evidence_id,
            storage=storage,
        )
        return Response(
            content=content,
            media_type=evidence.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{evidence.filename}"',
                "Cache-Control": "private, no-store",
            },
        )
    except WorkflowError as error:
        _raise_api_error(error)
