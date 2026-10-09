"""Batch 2 invitation, registration, and evidence domain services."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePath
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    AccessToken,
    Company,
    Evidence,
    EvidenceAsset,
    EvidenceStatus,
    EvidenceType,
    GateIdentityScan,
    Invitation,
    InvitationStatus,
    Person,
    PersonStanding,
    Population,
    Role,
    Site,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.providers import (
    DocumentExtractionError,
    DocumentExtractionProvider,
    StorageProvider,
)
from app.providers.storage import lock_private_reference, put_private_reference
from app.schemas.workflows import (
    EvidenceFieldsUpdate,
    InvitationCreate,
    InviteeRegistrationCreate,
    RegistrationCreate,
)
from app.services.audit import append_audit_event

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_UPLOADS: dict[str, frozenset[str]] = {
    ".txt": frozenset({"text/plain"}),
    ".json": frozenset({"application/json"}),
    ".pdf": frozenset({"application/pdf"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
}
_SYNTHETIC_MARKERS = (b"DEMO", b"NOT A REAL CREDENTIAL")
_PRIVILEGED_ROLES = frozenset(
    {Role.SYSTEM_ADMIN, Role.COMPLIANCE, Role.SITE_MANAGER}
)


# PUBLIC_INTERFACE
class WorkflowError(Exception):
    """Typed domain failure translated into a safe API response."""

    # PUBLIC_INTERFACE
    def __init__(self, status_code: int, detail: str) -> None:
        """Create a workflow error with an HTTP-compatible status."""

        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:32] or "record"


def _get_invitation(database: Session, invitation_id: uuid.UUID) -> Invitation:
    invitation = database.get(Invitation, invitation_id)
    if invitation is None:
        raise WorkflowError(404, "Invitation not found.")
    return invitation


def _get_evidence(database: Session, evidence_id: uuid.UUID) -> Evidence:
    evidence = database.get(Evidence, evidence_id)
    if evidence is None:
        raise WorkflowError(404, "Evidence not found.")
    return evidence


def _gate_invitation_for_token(
    database: Session,
    token_reference: str,
) -> Invitation:
    """Resolve a registered invitation using only the opaque token server-side."""

    normalized_reference = token_reference.strip()
    if not normalized_reference:
        raise WorkflowError(422, "A scanned access-token reference is required.")

    reference_hash = hashlib.sha256(
        normalized_reference.encode("utf-8")
    ).hexdigest()
    token = database.scalar(
        select(AccessToken).where(AccessToken.reference_hash == reference_hash)
    )
    if token is None:
        raise WorkflowError(404, "The scanned access token cannot be matched.")

    invitation = database.scalar(
        select(Invitation).where(Invitation.visit_id == token.visit_id)
    )
    if invitation is None or invitation.person_id is None:
        raise WorkflowError(
            409,
            "The scanned token is not linked to a registered evidence workflow.",
        )
    return invitation


def _account_email(database: Session, account: UserAccount) -> str | None:
    if account.person_id is None:
        return None
    person = database.get(Person, account.person_id)
    return person.email.lower() if person else None


def _can_read_invitation(
    database: Session,
    account: UserAccount,
    invitation: Invitation,
) -> bool:
    if account.role in _PRIVILEGED_ROLES:
        return True
    if invitation.requested_by_id == account.id:
        return True
    if account.person_id is not None and invitation.person_id == account.person_id:
        return True
    email = _account_email(database, account)
    return email is not None and email == invitation.invitee_email.lower()


def _require_invitation_access(
    database: Session,
    account: UserAccount,
    invitation: Invitation,
) -> None:
    if not _can_read_invitation(database, account, invitation):
        raise WorkflowError(403, "You cannot access this invitation.")


def _require_registration_access(
    database: Session,
    account: UserAccount,
    invitation: Invitation,
) -> None:
    if account.role in _PRIVILEGED_ROLES or invitation.requested_by_id == account.id:
        return
    _require_invitation_access(database, account, invitation)


def _require_evidence_access(
    database: Session,
    account: UserAccount,
    evidence: Evidence,
    *,
    review: bool = False,
) -> None:
    if account.role in _PRIVILEGED_ROLES:
        return
    if review:
        raise WorkflowError(403, "Evidence review requires a compliance role.")
    if account.person_id is not None and evidence.person_id == account.person_id:
        return
    raise WorkflowError(403, "You cannot access this evidence.")


def _dates_from_fields(fields: dict[str, Any]) -> tuple[date | None, date | None]:
    def parse(value: Any) -> date | None:
        if not isinstance(value, str):
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    return parse(fields.get("issue_date")), parse(fields.get("expiry_date"))


def _driving_licence_validity_assessment(
    fields: dict[str, Any],
    *,
    provider_mode: str,
) -> dict[str, Any]:
    """Create a review aid without declaring a document authentic or approved."""

    missing_fields: list[str] = []
    for field_name in ("holder_name", "document_number"):
        value = fields.get(field_name)
        if not isinstance(value, str) or not value.strip():
            missing_fields.append(field_name)

    categories = fields.get("categories")
    if not isinstance(categories, list) or not any(
        isinstance(category, str) and category.strip() for category in categories
    ):
        missing_fields.append("categories")

    _, expiry_date = _dates_from_fields(fields)
    expiry_is_current = expiry_date is not None and expiry_date >= date.today()
    assessment_source = (
        "ai_assisted_extraction"
        if provider_mode == "EXTERNAL"
        else "deterministic_demo_extraction"
    )

    if expiry_date is not None and expiry_date < date.today():
        status = "appears_expired"
        summary = (
            "The extracted Netherlands driving licence appears expired based on "
            "its displayed expiry date."
        )
    elif missing_fields or expiry_date is None:
        status = "needs_review"
        summary = (
            "The extracted Netherlands driving licence has incomplete details; "
            "a gatekeeper must review the document before making a decision."
        )
    else:
        status = "appears_valid"
        summary = (
            "The extracted Netherlands driving licence appears current based on "
            "its displayed expiry date and required details."
        )

    return {
        "assessment_status": status,
        "summary": summary,
        "assessment_source": assessment_source,
        "checks": {
            "required_fields_present": not missing_fields,
            "missing_fields": missing_fields,
            "expiry_date_current": expiry_is_current,
            "authenticity_verified": False,
            "gatekeeper_approval_required": True,
        },
        "limitations": [
            "This assessment is a review aid based on extracted visible fields.",
            "It does not authenticate the document or grant site access.",
        ],
    }


def _latest_replaceable_evidence(
    database: Session,
    person_id: uuid.UUID,
    evidence_type: EvidenceType,
) -> Evidence | None:
    statement = (
        select(Evidence)
        .where(
            Evidence.person_id == person_id,
            Evidence.evidence_type == evidence_type,
            Evidence.status.in_(
                [EvidenceStatus.REJECTED, EvidenceStatus.REUPLOAD_REQUESTED]
            ),
        )
        .order_by(Evidence.created_at.desc())
    )
    return database.scalar(statement)


def _new_evidence(
    database: Session,
    *,
    invitation: Invitation,
    actor: UserAccount,
    evidence_type: EvidenceType,
    filename: str,
    media_type: str,
    storage_reference: str,
    storage_mode: str,
    content_sha256: str,
    size_bytes: int,
    asset_id: uuid.UUID | None = None,
    synthetic: bool = True,
) -> Evidence:
    if invitation.person_id is None:
        raise WorkflowError(409, "Register the invitation before adding evidence.")

    replaced = _latest_replaceable_evidence(
        database,
        invitation.person_id,
        evidence_type,
    )
    now = _now()
    evidence = Evidence(
        id=uuid.uuid4(),
        person_id=invitation.person_id,
        invitation_id=invitation.id,
        asset_id=asset_id,
        evidence_type=evidence_type,
        status=EvidenceStatus.UPLOADED,
        filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
        content_sha256=content_sha256,
        storage_reference=storage_reference,
        storage_mode=storage_mode,
        provider_mode="PENDING",
        extracted_fields={},
        field_confidence={},
        validity_assessment={},
        issue_date=None,
        expiry_date=None,
        review_notes=None,
        supersedes_id=replaced.id if replaced else None,
        uploaded_by_id=actor.id,
        reviewed_by_id=None,
        created_at=now,
        updated_at=now,
    )
    if replaced is not None:
        replaced.status = EvidenceStatus.SUPERSEDED
        replaced.updated_at = now
    database.add(evidence)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="evidence.uploaded",
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason="Private evidence was attached to a registered invitation.",
        details={
            "invitation_id": str(invitation.id),
            "person_id": str(invitation.person_id),
            "evidence_type": evidence_type.value,
            "storage_mode": storage_mode,
            "supersedes_id": str(replaced.id) if replaced else None,
            "synthetic": synthetic,
        },
    )
    return evidence


# PUBLIC_INTERFACE
def create_invitation(
    database: Session,
    *,
    actor: UserAccount,
    payload: InvitationCreate,
) -> Invitation:
    """Create an INVITED workflow record and append its audit transition."""

    site = database.get(Site, payload.site_id)
    if site is None or not site.is_active:
        raise WorkflowError(404, "Active site not found.")

    # Use the same persisted clock as token issuance, even for direct API clients.
    from app.services.batch6 import get_effective_time

    if payload.ends_at <= get_effective_time(database):
        raise WorkflowError(
            422,
            "Visit end must be after the API effective demo time.",
        )

    now = _now()
    invitation_id = uuid.uuid4()
    invitation = Invitation(
        id=invitation_id,
        seed_key=f"invitation_{invitation_id.hex}",
        site_id=site.id,
        requested_by_id=actor.id,
        invitee_email=str(payload.invitee_email).lower(),
        population=payload.population,
        company_name=payload.company_name.strip(),
        purpose=payload.purpose.strip(),
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        status=InvitationStatus.INVITED,
        response_status="pending",
        delivery_status="local_only",
        company_id=None,
        person_id=None,
        visit_id=None,
        created_at=now,
        updated_at=now,
    )
    database.add(invitation)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="invitation.created",
        entity_type="invitation",
        entity_id=str(invitation.id),
        reason="Created a synthetic site-access invitation.",
        details={
            "site_id": str(site.id),
            "population": invitation.population.value,
            "status": invitation.status.value,
            "synthetic": True,
        },
    )
    return invitation


# PUBLIC_INTERFACE
def issue_invitation_response_token(database: Session, invitation: Invitation) -> str:
    """Assign a short-lived random bearer secret, persisting only its SHA-256 digest."""

    token = secrets.token_urlsafe(32)
    invitation.response_token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    invitation.response_token_expires_at = min(
        invitation.ends_at,
        _now() + timedelta(days=7),
    )
    database.flush()
    return token


# PUBLIC_INTERFACE
def inspect_invitation_response(
    database: Session, *, token: str, decision: str
) -> tuple[Invitation, str]:
    """Return the safe state of an email link without consuming it."""

    if decision not in {"accept", "decline"} or len(token) > 256 or len(token) < 32:
        raise WorkflowError(404, "Invitation link is invalid.")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    invitation = database.scalar(
        select(Invitation).where(Invitation.response_token_hash == digest)
    )
    if invitation is None:
        raise WorkflowError(404, "Invitation link is invalid.")
    if invitation.response_status != "pending":
        return invitation, "already_responded"
    if (
        invitation.response_token_expires_at is None
        or invitation.response_token_expires_at <= _now()
    ):
        return invitation, "expired"
    return invitation, "pending"


# PUBLIC_INTERFACE
def record_invitation_response(
    database: Session, *, token: str, decision: str
) -> Invitation:
    """Atomically consume an invitation token and record exactly one decision."""

    if decision not in {"accept", "decline"} or len(token) > 256 or len(token) < 32:
        raise WorkflowError(404, "Invitation link is invalid.")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    # Row locking serializes competing Accept and Decline requests.
    invitation = database.scalar(
        select(Invitation)
        .where(Invitation.response_token_hash == digest)
        .with_for_update()
    )
    if invitation is None:
        raise WorkflowError(404, "Invitation link is invalid.")
    if invitation.response_status != "pending":
        raise WorkflowError(409, "Invitation has already been responded to.")
    now = _now()
    if invitation.response_token_expires_at is None or invitation.response_token_expires_at <= now:
        raise WorkflowError(410, "Invitation link has expired.")
    invitation.response_status = "accepted" if decision == "accept" else "declined"
    invitation.responded_at = now
    invitation.updated_at = now
    if decision == "accept":
        # The email decision secret is single-use; a separate short-lived
        # capability permits the accepted recipient to submit registration.
        registration_token = secrets.token_urlsafe(32)
        invitation.registration_token_hash = hashlib.sha256(
            registration_token.encode("ascii")
        ).hexdigest()
        invitation.registration_token_expires_at = min(
            invitation.ends_at, now + timedelta(days=7)
        )
    else:
        registration_token = None
    append_audit_event(
        database,
        actor=None,
        action=f"invitation.{invitation.response_status}",
        entity_type="invitation",
        entity_id=str(invitation.id),
        reason="Recipient confirmed a single-use email response.",
        details={"response_status": invitation.response_status},
    )
    return invitation, registration_token


# PUBLIC_INTERFACE
def get_invitee_registration(
    database: Session, *, token: str, lock: bool = False
) -> Invitation:
    """Resolve a live accepted-invitation capability without exposing its hash."""

    if len(token) < 32 or len(token) > 256:
        raise WorkflowError(404, "Registration link is invalid.")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    statement = select(Invitation).where(
        Invitation.registration_token_hash == digest
    )
    if lock:
        statement = statement.with_for_update()
    invitation = database.scalar(statement)
    if invitation is None or invitation.response_status != "accepted":
        raise WorkflowError(404, "Registration link is invalid.")
    if (
        invitation.registration_token_expires_at is None
        or invitation.registration_token_expires_at <= _now()
    ):
        raise WorkflowError(410, "Registration link has expired.")
    return invitation


# PUBLIC_INTERFACE
def register_accepted_invitee(
    database: Session,
    *,
    token: str,
    payload: InviteeRegistrationCreate,
    evidence_type: EvidenceType,
    filename: str,
    media_type: str,
    content: bytes,
    storage: StorageProvider,
    allow_real_identity_document: bool,
) -> Invitation:
    """Register the accepted recipient and attach required evidence atomically.

    The recipient cannot select another person, company, email, or reviewer.
    Evidence remains unverified until an authorized human reviews it.
    """

    invitation = get_invitee_registration(database, token=token, lock=True)
    if invitation.registration_completed_at is not None or invitation.person_id is not None:
        raise WorkflowError(409, "Registration has already been submitted.")
    if invitation.ends_at <= _now():
        raise WorkflowError(410, "The invitation visit window has ended.")

    expected_type = (
        EvidenceType.DRIVING_LICENCE
        if invitation.population in {
            Population.RENEWI_DRIVER,
            Population.TEMPORARY_DRIVER,
            Population.EXTERNAL_DRIVER,
        }
        else EvidenceType.ID_CARD
    )
    if evidence_type is not expected_type:
        raise WorkflowError(422, "Upload the required identity document for this invitation.")

    safe_filename = PurePath(filename).name
    suffix = PurePath(safe_filename).suffix.lower()
    if (
        not safe_filename
        or filename != safe_filename
        or len(filename) > 180
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise WorkflowError(422, "Upload filename is invalid.")
    if suffix not in ALLOWED_UPLOADS or media_type not in ALLOWED_UPLOADS[suffix]:
        raise WorkflowError(415, "Upload extension and MIME type are not allowed.")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise WorkflowError(413, "Upload must contain between 1 byte and 5 MiB.")
    is_synthetic = any(
        marker in content[:65536].upper() for marker in _SYNTHETIC_MARKERS
    )
    if not is_synthetic and not allow_real_identity_document:
        raise WorkflowError(503, "Real identity-document extraction is not configured.")

    company = database.scalar(
        select(Company).where(
            func.lower(Company.name) == invitation.company_name.lower()
        )
    )
    if company is None:
        company_id = uuid.uuid4()
        company = Company(
            id=company_id,
            seed_key=f"company_registration_{company_id.hex}",
            name=invitation.company_name,
            company_type="contractor",
            country_code="NL",
            is_active=True,
        )
        database.add(company)
        database.flush()

    first_name = payload.first_name.strip()
    last_name = payload.last_name.strip()
    # Never identify a person by email alone, even when multiple people
    # share the invited address.
    candidates = database.scalars(
        select(Person).where(
            Person.company_id == company.id,
            func.lower(Person.email) == invitation.invitee_email.lower(),
            Person.population == invitation.population,
        )
    )
    person = next(
        (
            candidate for candidate in candidates
            if candidate.first_name.strip().casefold() == first_name.casefold()
            and candidate.last_name.strip().casefold() == last_name.casefold()
        ),
        None,
    )
    if person is None:
        person_id = uuid.uuid4()
        person = Person(
            id=person_id,
            seed_key=f"person_registration_{person_id.hex}",
            company_id=company.id,
            first_name=first_name,
            last_name=last_name,
            email=invitation.invitee_email,
            population=invitation.population,
            standing=PersonStanding.ACTIVE,
            source_metadata={"source": "accepted_invitation_registration"},
        )
        database.add(person)
        database.flush()

    visit_id = uuid.uuid4()
    visit = Visit(
        id=visit_id,
        seed_key=f"visit_registration_{visit_id.hex}",
        person_id=person.id,
        site_id=invitation.site_id,
        host_person_id=None,
        purpose=invitation.purpose,
        status=VisitStatus.PLANNED,
        starts_at=invitation.starts_at,
        ends_at=invitation.ends_at,
    )
    database.add(visit)
    database.flush()

    # Store privately; the public registration response exposes neither
    # document bytes nor their storage reference or identity details.
    stored = put_private_reference(database, storage, content)
    now = _now()
    evidence = Evidence(
        id=uuid.uuid4(),
        person_id=person.id,
        invitation_id=invitation.id,
        asset_id=None,
        evidence_type=evidence_type,
        status=EvidenceStatus.UPLOADED,
        filename=safe_filename,
        media_type=media_type,
        size_bytes=stored.size_bytes,
        content_sha256=stored.sha256,
        storage_reference=stored.reference,
        storage_mode=stored.mode,
        provider_mode="PENDING",
        extracted_fields={},
        field_confidence={},
        # This is an invitee assertion, not an extraction or reviewer decision.
        validity_assessment={
            "source": "invitee_registration",
            "expiry_unverified": True,
        },
        issue_date=None,
        expiry_date=payload.expiry_date,
        review_notes=None,
        supersedes_id=None,
        uploaded_by_id=invitation.requested_by_id,
        reviewed_by_id=None,
        created_at=now,
        updated_at=now,
    )
    database.add(evidence)
    invitation.company_id = company.id
    invitation.person_id = person.id
    invitation.visit_id = visit.id
    invitation.status = InvitationStatus.PRE_REGISTERED
    invitation.registration_completed_at = now
    invitation.updated_at = now
    append_audit_event(
        database,
        actor=None,
        action="registration.recipient_completed",
        entity_type="invitation",
        entity_id=str(invitation.id),
        reason="Accepted invitee supplied details and an identity document for review.",
        details={
            "person_id": str(person.id),
            "evidence_id": str(evidence.id),
            "evidence_type": evidence_type.value,
        },
    )
    return invitation


# PUBLIC_INTERFACE
def list_visible_invitations(
    database: Session,
    *,
    actor: UserAccount,
) -> list[Invitation]:
    """List invitations within the authenticated account's object scope."""

    invitations = list(
        database.scalars(
            select(Invitation).order_by(Invitation.created_at.desc(), Invitation.id)
        ).all()
    )
    return [
        invitation
        for invitation in invitations
        if _can_read_invitation(database, actor, invitation)
    ]


# PUBLIC_INTERFACE
def get_visible_invitation(
    database: Session,
    *,
    actor: UserAccount,
    invitation_id: uuid.UUID,
) -> Invitation:
    """Return one invitation after object-level authorization."""

    invitation = _get_invitation(database, invitation_id)
    _require_invitation_access(database, actor, invitation)
    return invitation


# PUBLIC_INTERFACE
def register_invitation(
    database: Session,
    *,
    actor: UserAccount,
    invitation_id: uuid.UUID,
    payload: RegistrationCreate,
) -> tuple[Invitation, Company, Person, Visit, bool, bool]:
    """Create or link company/person records and establish one planned visit."""

    invitation = _get_invitation(database, invitation_id)
    _require_registration_access(database, actor, invitation)
    if invitation.response_status != "accepted":
        raise WorkflowError(409, "The recipient must accept before registration.")
    if invitation.registration_completed_at is None:
        raise WorkflowError(409, "The invitee must submit registration and evidence.")
    if (
        invitation.company_id is not None
        and invitation.person_id is not None
        and invitation.visit_id is not None
    ):
        company = database.get(Company, invitation.company_id)
        person = database.get(Person, invitation.person_id)
        visit = database.get(Visit, invitation.visit_id)
        if company and person and visit:
            return invitation, company, person, visit, False, False

    company_created = False
    if payload.company_id is not None:
        company = database.get(Company, payload.company_id)
        if company is None:
            raise WorkflowError(404, "Company not found.")
    else:
        company_name = (payload.company_name or invitation.company_name).strip()
        company = database.scalar(
            select(Company).where(func.lower(Company.name) == company_name.lower())
        )
        if company is None:
            company_id = uuid.uuid4()
            company = Company(
                id=company_id,
                seed_key=f"company_registration_{company_id.hex}",
                name=company_name,
                company_type=payload.company_type,
                country_code=payload.company_country_code,
                is_active=True,
            )
            database.add(company)
            database.flush()
            company_created = True

    person_created = False
    if payload.person_id is not None:
        person = database.get(Person, payload.person_id)
        if person is None:
            raise WorkflowError(404, "Person not found.")
        if person.company_id != company.id:
            raise WorkflowError(
                409,
                "The selected person belongs to a different company.",
            )
    else:
        email = str(payload.email or invitation.invitee_email).lower()
        first_name = (payload.first_name or "").strip()
        last_name = (payload.last_name or "").strip()
        # Email is a contact address, not a unique person identifier. Reuse
        # only a person with the same company, email, and entered name.
        candidates = database.scalars(
            select(Person).where(
                Person.company_id == company.id,
                func.lower(Person.email) == email,
            )
        )
        person = next(
            (
                candidate
                for candidate in candidates
                if candidate.first_name.strip().casefold() == first_name.casefold()
                and candidate.last_name.strip().casefold() == last_name.casefold()
            ),
            None,
        )
        if person is None:
            person_id = uuid.uuid4()
            person = Person(
                id=person_id,
                seed_key=f"person_registration_{person_id.hex}",
                company_id=company.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                population=invitation.population,
                standing=PersonStanding.ACTIVE,
                source_metadata={
                    "mode": "DEMO",
                    "source": "invitation_registration",
                    "synthetic": True,
                },
            )
            database.add(person)
            database.flush()
            person_created = True

    visit_id = uuid.uuid4()
    visit = Visit(
        id=visit_id,
        seed_key=f"visit_registration_{visit_id.hex}",
        person_id=person.id,
        site_id=invitation.site_id,
        host_person_id=actor.person_id if actor.role is Role.HOST else None,
        purpose=invitation.purpose,
        status=VisitStatus.PLANNED,
        starts_at=invitation.starts_at,
        ends_at=invitation.ends_at,
    )
    database.add(visit)
    database.flush()

    invitation.company_id = company.id
    invitation.person_id = person.id
    invitation.visit_id = visit.id
    invitation.status = InvitationStatus.PRE_REGISTERED
    invitation.updated_at = _now()
    append_audit_event(
        database,
        actor=actor,
        action="registration.completed",
        entity_type="invitation",
        entity_id=str(invitation.id),
        reason="Linked the invitation to company, person, site, and visit records.",
        details={
            "company_id": str(company.id),
            "person_id": str(person.id),
            "visit_id": str(visit.id),
            "company_created": company_created,
            "person_created": person_created,
            "status": invitation.status.value,
            "synthetic": True,
        },
    )
    return invitation, company, person, visit, company_created, person_created


# PUBLIC_INTERFACE
def attach_synthetic_asset(
    database: Session,
    *,
    actor: UserAccount,
    invitation_id: uuid.UUID,
    asset_id: uuid.UUID,
) -> Evidence:
    """Attach an existing private fictional asset to a registered invitation."""

    invitation = _get_invitation(database, invitation_id)
    _require_registration_access(database, actor, invitation)
    if invitation.response_status != "accepted" or invitation.registration_completed_at is None:
        raise WorkflowError(409, "The accepted invitee must complete registration first.")
    asset = database.get(EvidenceAsset, asset_id)
    if asset is None or not asset.is_active:
        raise WorkflowError(404, "Active synthetic evidence asset not found.")
    # Attaching an asset creates a reference without writing new bytes.
    lock_private_reference(database, asset.storage_reference)
    return _new_evidence(
        database,
        invitation=invitation,
        actor=actor,
        evidence_type=asset.evidence_type,
        filename=asset.filename,
        media_type=asset.media_type,
        storage_reference=asset.storage_reference,
        storage_mode="LOCAL",
        content_sha256=asset.content_sha256,
        size_bytes=asset.size_bytes,
        asset_id=asset.id,
    )


# PUBLIC_INTERFACE
def upload_evidence(
    database: Session,
    *,
    actor: UserAccount,
    invitation_id: uuid.UUID,
    evidence_type: EvidenceType,
    filename: str,
    media_type: str,
    content: bytes,
    storage: StorageProvider,
    allow_real_identity_document: bool,
) -> Evidence:
    """Validate and privately store invitation evidence of any file format."""

    invitation = _get_invitation(database, invitation_id)
    _require_registration_access(database, actor, invitation)
    if invitation.response_status != "accepted" or invitation.registration_completed_at is None:
        raise WorkflowError(409, "The accepted invitee must complete registration first.")

    # Identity submissions are role-specific; certificate uploads are unaffected.
    if evidence_type in {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}:
        driver = invitation.population in {
            Population.RENEWI_DRIVER,
            Population.TEMPORARY_DRIVER,
            Population.EXTERNAL_DRIVER,
        }
        expected = EvidenceType.DRIVING_LICENCE if driver else EvidenceType.ID_CARD
        if evidence_type is not expected:
            raise WorkflowError(
                422,
                "Drivers must upload a driving licence; other people must upload an ID card.",
            )

    safe_filename = PurePath(filename).name
    suffix = PurePath(safe_filename).suffix.lower()
    if (
        not safe_filename
        or safe_filename != filename
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        or len(filename) > 255
    ):
        raise WorkflowError(422, "Upload filename is invalid.")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise WorkflowError(413, "Upload must contain between 1 byte and 5 MiB.")
    upper_sample = content[:65536].upper()
    is_synthetic = any(marker in upper_sample for marker in _SYNTHETIC_MARKERS)
    real_identity_types = {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}
    # An arbitrary file containing a marker is not necessarily a synthetic
    # document; unfamiliar formats are stored without extraction claims.
    extractable_format = (
        suffix in ALLOWED_UPLOADS
        and media_type in ALLOWED_UPLOADS[suffix]
    )
    if extractable_format and not is_synthetic and evidence_type not in real_identity_types:
        raise WorkflowError(
            422,
            "Evidence must be visibly marked DEMO or NOT A REAL CREDENTIAL.",
        )
    if (
        extractable_format
        and not is_synthetic
        and evidence_type in real_identity_types
        and not allow_real_identity_document
    ):
        raise WorkflowError(
            503,
            "Real identity-document extraction is not configured for this service.",
        )

    stored = put_private_reference(database, storage, content)
    return _new_evidence(
        database,
        invitation=invitation,
        actor=actor,
        evidence_type=evidence_type,
        filename=safe_filename,
        media_type=media_type,
        storage_reference=stored.reference,
        storage_mode=stored.mode,
        content_sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        synthetic=is_synthetic and extractable_format,
    )


# PUBLIC_INTERFACE
def upload_invitation_identity_document(
    database: Session,
    *,
    actor: UserAccount,
    invitation_id: uuid.UUID,
    filename: str,
    media_type: str,
    content: bytes,
    storage: StorageProvider,
) -> Invitation:
    """Store an invitation ID privately for later deterministic gate matching.

    This flow deliberately performs no document extraction or identity
    verification. The private content digest is the sole match reference used
    by the dedicated gate scan endpoint.
    """

    invitation = _get_invitation(database, invitation_id)
    _require_invitation_access(database, actor, invitation)
    if invitation.response_status != "accepted" or invitation.registration_completed_at is None:
        raise WorkflowError(409, "The accepted invitee must complete registration first.")

    safe_filename = PurePath(filename).name
    suffix = PurePath(safe_filename).suffix.lower()
    if not safe_filename or safe_filename != filename:
        raise WorkflowError(422, "Upload filename is invalid.")
    if suffix not in ALLOWED_UPLOADS or media_type not in ALLOWED_UPLOADS[suffix]:
        raise WorkflowError(415, "Upload extension and MIME type are not allowed.")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise WorkflowError(413, "Upload must contain between 1 byte and 5 MiB.")

    stored = put_private_reference(database, storage, content)
    uploaded_at = _now()
    invitation.identity_document_sha256 = stored.sha256
    invitation.identity_document_storage_reference = stored.reference
    invitation.identity_document_media_type = media_type
    invitation.identity_document_uploaded_at = uploaded_at
    invitation.updated_at = uploaded_at
    # A replacement invitation ID must invalidate every earlier gate scan.
    database.execute(
        delete(GateIdentityScan).where(GateIdentityScan.invitation_id == invitation.id)
    )
    append_audit_event(
        database,
        actor=actor,
        action="invitation.identity_document_uploaded",
        entity_type="invitation",
        entity_id=str(invitation.id),
        reason="A private invitation identity document was uploaded for gate matching.",
        details={
            "media_type": media_type,
            "size_bytes": stored.size_bytes,
            "storage_mode": stored.mode,
        },
    )
    return invitation


# PUBLIC_INTERFACE
def match_gate_identity_document(
    database: Session,
    *,
    actor: UserAccount,
    token_reference: str,
    filename: str,
    media_type: str,
    content: bytes,
) -> dict[str, str | bool]:
    """Match a gate-scanned private ID against the scanned token's invitation.

    The comparison is server-side and uses constant-time digest comparison.
    No extraction provider, including Anthropic, participates in this flow.
    """

    invitation = _gate_invitation_for_token(database, token_reference)
    safe_filename = PurePath(filename).name
    suffix = PurePath(safe_filename).suffix.lower()
    if not safe_filename or safe_filename != filename:
        raise WorkflowError(422, "Upload filename is invalid.")
    if suffix not in ALLOWED_UPLOADS or media_type not in ALLOWED_UPLOADS[suffix]:
        raise WorkflowError(415, "Upload extension and MIME type are not allowed.")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise WorkflowError(413, "Upload must contain between 1 byte and 5 MiB.")

    expected_digest = invitation.identity_document_sha256
    scanned_digest = hashlib.sha256(content).hexdigest()
    matched = bool(
        expected_digest and hmac.compare_digest(expected_digest, scanned_digest)
    )
    # Keep only the latest presentation for this operator and token. A failed
    # rescan must never leave a previously successful match usable at the gate.
    token_hash = hashlib.sha256(token_reference.strip().encode("utf-8")).hexdigest()
    database.execute(
        delete(GateIdentityScan).where(
            GateIdentityScan.token_reference_hash == token_hash,
            GateIdentityScan.operator_id == actor.id,
        )
    )
    database.add(
        GateIdentityScan(
            id=uuid.uuid4(),
            invitation_id=invitation.id,
            operator_id=actor.id,
            token_reference_hash=token_hash,
            invitation_identity_sha256=expected_digest,
            matched=matched,
            scanned_at=_now(),
            consumed_at=None,
        )
    )
    result = {
        "matched": matched,
        "reason_code": "INVITATION_ID_MATCHED" if matched else "INVITATION_ID_MISMATCH",
        "detail": (
            "The scanned ID matches the private ID uploaded with this invitation."
            if matched
            else (
                "No private ID has been uploaded with this invitation."
                if expected_digest is None
                else "The scanned ID does not match the invitation's uploaded ID."
            )
        ),
    }
    append_audit_event(
        database,
        actor=actor,
        action=(
            "gate.identity_document_matched"
            if matched
            else "gate.identity_document_mismatched"
        ),
        entity_type="invitation",
        entity_id=str(invitation.id),
        reason=str(result["detail"]),
        details={
            "token_scanned": True,
            "matched": matched,
            "media_type": media_type,
        },
    )
    return result


# PUBLIC_INTERFACE
def upload_gate_identity_evidence(
    database: Session,
    *,
    actor: UserAccount,
    token_reference: str,
    evidence_type: EvidenceType,
    filename: str,
    media_type: str,
    content: bytes,
    storage: StorageProvider,
    allow_real_identity_document: bool,
) -> Evidence:
    """Privately store a gate-presented Dutch ID or driving licence.

    The server resolves the invitation from the opaque scanned token; clients
    never supply person or invitation identifiers for this gate workflow.
    """

    if evidence_type not in {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}:
        raise WorkflowError(
            422,
            "Gate document upload supports only an ID card or driving licence.",
        )

    invitation = _gate_invitation_for_token(database, token_reference)
    driver = invitation.population in {
        Population.RENEWI_DRIVER,
        Population.TEMPORARY_DRIVER,
        Population.EXTERNAL_DRIVER,
    }
    expected = EvidenceType.DRIVING_LICENCE if driver else EvidenceType.ID_CARD
    if evidence_type is not expected:
        raise WorkflowError(
            422,
            "Drivers must upload a driving licence; other people must upload an ID card.",
        )
    safe_filename = PurePath(filename).name
    suffix = PurePath(safe_filename).suffix.lower()
    if not safe_filename or safe_filename != filename:
        raise WorkflowError(422, "Upload filename is invalid.")
    if suffix not in ALLOWED_UPLOADS or media_type not in ALLOWED_UPLOADS[suffix]:
        raise WorkflowError(415, "Upload extension and MIME type are not allowed.")
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise WorkflowError(413, "Upload must contain between 1 byte and 5 MiB.")

    is_synthetic = any(
        marker in content[:65536].upper() for marker in _SYNTHETIC_MARKERS
    )
    if not is_synthetic and not allow_real_identity_document:
        raise WorkflowError(
            503,
            "Real identity-document extraction is not configured for this service.",
        )

    stored = put_private_reference(database, storage, content)
    return _new_evidence(
        database,
        invitation=invitation,
        actor=actor,
        evidence_type=evidence_type,
        filename=safe_filename,
        media_type=media_type,
        storage_reference=stored.reference,
        storage_mode=stored.mode,
        content_sha256=stored.sha256,
        size_bytes=stored.size_bytes,
        synthetic=is_synthetic,
    )


# PUBLIC_INTERFACE
def list_assets(database: Session) -> list[EvidenceAsset]:
    """List active synthetic assets in stable catalog order."""

    return list(
        database.scalars(
            select(EvidenceAsset)
            .where(EvidenceAsset.is_active.is_(True))
            .order_by(EvidenceAsset.evidence_type, EvidenceAsset.asset_key)
        ).all()
    )


# PUBLIC_INTERFACE
def list_person_evidence(
    database: Session,
    *,
    actor: UserAccount,
    person_id: uuid.UUID,
) -> list[Evidence]:
    """List authorized evidence metadata without exposing storage references."""

    if actor.role not in _PRIVILEGED_ROLES and actor.person_id != person_id:
        raise WorkflowError(403, "You cannot access this person's evidence.")
    return list(
        database.scalars(
            select(Evidence)
            .where(Evidence.person_id == person_id)
            .order_by(Evidence.created_at.desc(), Evidence.id)
        ).all()
    )


# PUBLIC_INTERFACE
def extract_evidence(
    database: Session,
    *,
    actor: UserAccount,
    evidence_id: uuid.UUID,
    parser: DocumentExtractionProvider,
) -> Evidence:
    """Run configured extraction while leaving verification to a reviewer."""

    evidence = _get_evidence(database, evidence_id)
    _require_evidence_access(database, actor, evidence)
    if evidence.status is EvidenceStatus.SUPERSEDED:
        raise WorkflowError(409, "Superseded evidence cannot be extracted.")

    expected_fields: dict[str, Any] | None = None
    if evidence.asset_id is not None:
        asset = database.get(EvidenceAsset, evidence.asset_id)
        expected_fields = asset.expected_fields if asset else None
    try:
        result = parser.extract(
            storage_reference=evidence.storage_reference,
            evidence_type=evidence.evidence_type,
            media_type=evidence.media_type,
            expected_fields=expected_fields,
        )
    except DocumentExtractionError as error:
        raise WorkflowError(503, str(error)) from error
    issue_date, expiry_date = _dates_from_fields(result.fields)
    evidence.extracted_fields = result.fields
    evidence.field_confidence = result.field_confidence
    evidence.provider_mode = result.provider_mode
    evidence.validity_assessment = (
        _driving_licence_validity_assessment(
            result.fields,
            provider_mode=result.provider_mode,
        )
        if evidence.evidence_type is EvidenceType.DRIVING_LICENCE
        else {}
    )
    evidence.issue_date = issue_date
    evidence.expiry_date = expiry_date
    evidence.status = EvidenceStatus.EXTRACTED
    evidence.updated_at = _now()
    append_audit_event(
        database,
        actor=actor,
        action="evidence.extracted",
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason="Configured extraction produced editable evidence fields for review.",
        details={
            "provider_mode": result.provider_mode,
            "field_names": sorted(result.fields),
            "assessment_status": evidence.validity_assessment.get(
                "assessment_status"
            ),
            "synthetic": result.provider_mode == "DEMO",
        },
    )
    return evidence


# PUBLIC_INTERFACE
def extract_gate_identity_evidence(
    database: Session,
    *,
    actor: UserAccount,
    token_reference: str,
    evidence_id: uuid.UUID,
    parser: DocumentExtractionProvider,
) -> Evidence:
    """Extract token-bound gate evidence without verifying it or granting access."""

    invitation = _gate_invitation_for_token(database, token_reference)
    evidence = _get_evidence(database, evidence_id)
    supported_types = {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}
    if (
        evidence.invitation_id != invitation.id
        or evidence.evidence_type not in supported_types
    ):
        raise WorkflowError(404, "Gate identity evidence was not found.")
    if evidence.status is EvidenceStatus.SUPERSEDED:
        raise WorkflowError(409, "Superseded evidence cannot be extracted.")

    try:
        result = parser.extract(
            storage_reference=evidence.storage_reference,
            evidence_type=evidence.evidence_type,
            media_type=evidence.media_type,
        )
    except DocumentExtractionError as error:
        raise WorkflowError(503, str(error)) from error

    issue_date, expiry_date = _dates_from_fields(result.fields)
    evidence.extracted_fields = result.fields
    evidence.field_confidence = result.field_confidence
    evidence.provider_mode = result.provider_mode
    evidence.validity_assessment = (
        _driving_licence_validity_assessment(
            result.fields,
            provider_mode=result.provider_mode,
        )
        if evidence.evidence_type is EvidenceType.DRIVING_LICENCE
        else {}
    )
    evidence.issue_date = issue_date
    evidence.expiry_date = expiry_date
    evidence.status = EvidenceStatus.EXTRACTED
    evidence.updated_at = _now()
    append_audit_event(
        database,
        actor=actor,
        action="evidence.extracted",
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason="Gate identity extraction produced fields for authorized review.",
        details={
            "provider_mode": result.provider_mode,
            "field_names": sorted(result.fields),
            "assessment_status": evidence.validity_assessment.get(
                "assessment_status"
            ),
            "synthetic": result.provider_mode == "DEMO",
        },
    )
    return evidence


# PUBLIC_INTERFACE
def update_evidence_fields(
    database: Session,
    *,
    actor: UserAccount,
    evidence_id: uuid.UUID,
    payload: EvidenceFieldsUpdate,
) -> Evidence:
    """Replace editable extracted fields and persist reviewed validity dates."""

    evidence = _get_evidence(database, evidence_id)
    _require_evidence_access(database, actor, evidence, review=True)
    if evidence.status is not EvidenceStatus.EXTRACTED:
        raise WorkflowError(409, "Only extracted evidence can be edited.")
    evidence.extracted_fields = payload.fields
    evidence.issue_date = payload.issue_date
    evidence.expiry_date = payload.expiry_date
    evidence.reviewed_by_id = actor.id
    evidence.updated_at = _now()
    append_audit_event(
        database,
        actor=actor,
        action="evidence.fields_edited",
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason="A compliance reviewer corrected extracted evidence fields.",
        details={
            "field_names": sorted(payload.fields),
            "issue_date": (
                payload.issue_date.isoformat() if payload.issue_date else None
            ),
            "expiry_date": (
                payload.expiry_date.isoformat() if payload.expiry_date else None
            ),
            "synthetic": True,
        },
    )
    return evidence


# PUBLIC_INTERFACE
def review_evidence(
    database: Session,
    *,
    actor: UserAccount,
    evidence_id: uuid.UUID,
    target_status: EvidenceStatus,
    reason: str,
) -> Evidence:
    """Verify, reject, or request replacement evidence with audit evidence."""

    evidence = _get_evidence(database, evidence_id)
    _require_evidence_access(database, actor, evidence, review=True)
    allowed = {
        EvidenceStatus.VERIFIED,
        EvidenceStatus.REJECTED,
        EvidenceStatus.REUPLOAD_REQUESTED,
    }
    if target_status not in allowed:
        raise WorkflowError(422, "Unsupported evidence review transition.")
    if target_status is EvidenceStatus.VERIFIED:
        if evidence.status not in {EvidenceStatus.UPLOADED, EvidenceStatus.EXTRACTED}:
            raise WorkflowError(409, "Only uploaded or extracted evidence can be verified.")
        # Review is an explicit authorized human decision, not an extraction result.
    elif evidence.status is EvidenceStatus.SUPERSEDED:
        raise WorkflowError(409, "Superseded evidence cannot be reviewed.")

    evidence.status = target_status
    evidence.review_notes = reason
    evidence.reviewed_by_id = actor.id
    evidence.updated_at = _now()

    action = {
        EvidenceStatus.VERIFIED: "evidence.verified",
        EvidenceStatus.REJECTED: "evidence.rejected",
        EvidenceStatus.REUPLOAD_REQUESTED: "evidence.reupload_requested",
    }[target_status]
    append_audit_event(
        database,
        actor=actor,
        action=action,
        entity_type="evidence",
        entity_id=str(evidence.id),
        reason=reason,
        details={
            "person_id": str(evidence.person_id),
            "evidence_type": evidence.evidence_type.value,
            "issue_date": evidence.issue_date.isoformat() if evidence.issue_date else None,
            "expiry_date": (
                evidence.expiry_date.isoformat() if evidence.expiry_date else None
            ),
            "status": target_status.value,
            "synthetic": True,
        },
    )

    if (
        target_status is EvidenceStatus.VERIFIED
        and evidence.invitation_id is not None
    ):
        invitation = database.get(Invitation, evidence.invitation_id)
        if invitation is not None and invitation.status is not InvitationStatus.EVIDENCE_READY:
            invitation.status = InvitationStatus.EVIDENCE_READY
            invitation.updated_at = _now()
            append_audit_event(
                database,
                actor=actor,
                action="invitation.evidence_ready",
                entity_type="invitation",
                entity_id=str(invitation.id),
                reason="Verified evidence advanced the invitation to evidence-ready.",
                details={
                    "evidence_id": str(evidence.id),
                    "status": invitation.status.value,
                    "synthetic": True,
                },
            )
    return evidence


# PUBLIC_INTERFACE
def read_evidence_content(
    database: Session,
    *,
    actor: UserAccount,
    evidence_id: uuid.UUID,
    storage: StorageProvider,
) -> tuple[Evidence, bytes]:
    """Retrieve private evidence content after object-level authorization."""

    evidence = _get_evidence(database, evidence_id)
    _require_evidence_access(database, actor, evidence)
    try:
        content = storage.get(evidence.storage_reference)
    except (FileNotFoundError, ValueError) as error:
        raise WorkflowError(404, "Private evidence content is unavailable.") from error
    return evidence, content
