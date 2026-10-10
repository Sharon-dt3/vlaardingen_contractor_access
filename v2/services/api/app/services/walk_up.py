"""QR walk-up registration: someone arrives with no invitation, registers and confirms the rules.

This is a second way in, next to the invitation flow, for people the site did not
know about in advance. It asks for basic details and the life-saving confirmation,
nothing else. The confirmation is the same record the invitation flow writes
(``LifeSavingRulesAcknowledgement``), so the people list, the person page and the
compliance check all see walk-up people exactly like invited ones.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

import qrcode
from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    GateDecision,
    Company,
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
    Person,
    PersonStanding,
    Population,
    Site,
    UserAccount,
    WalkUpPending,
    WalkUpRegistration,
)
from app.services.audit import append_audit_event
from app.services.batch3 import _is_blacklisted
from app.services.life_saving import content_sha256, pick_translation, status_for_people
from app.services.workflows import WorkflowError

CONFIRMATION_METHOD_WALK_UP = "walk_up_qr"
PERSON_SOURCE = "walk_up_qr"
# How long a registration can be presented at the kiosk. A new day needs a new registration.
PASS_VALID_HOURS = 12
PASS_PREFIX = "renewi-walkup:"
# The email check: a six-digit code, valid for a few minutes, with limited tries and resends.
CODE_VALID_MINUTES = 10
MAX_CODE_ATTEMPTS = 5
MAX_CODE_SENDS = 3
RESEND_COOLDOWN_SECONDS = 30
MAX_CODES_PER_EMAIL_PER_HOUR = 5
# A repeated lookup of the same refused person within this time is not recorded again.
REFUSAL_DEDUPE_SECONDS = 60
# The same for a repeated check of a person who may enter.
LOOKUP_DEDUPE_SECONDS = 60
# Why an officer may turn away someone the records would allow in.
OFFICER_REFUSAL_REASONS = {
    "identity_mismatch": "The person does not match the registration or their ID.",
    "not_expected": "Nobody could confirm they are expected.",
    "other": "Another reason, written in the note.",
}
# Someone still listed on site after this long is flagged for the officer to check.
STALE_ON_SITE_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def site_key(site: Site) -> str:
    """The short, readable address of a site in its QR link, such as ``vlaardingen``."""

    return re.sub(r"[^a-z0-9]+", "-", site.name.lower()).strip("-")


def reference_for(registration_id: uuid.UUID) -> str:
    """A short code the person can show a guard to point at their registration."""

    return registration_id.hex[:8].upper()


def _hash_pass(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def pass_qr_png(pass_secret: str, reference: str) -> bytes:
    """The entry QR as PNG bytes: ``renewi-walkup:<reference>:<secret>``.

    The reference is not secret, so the kiosk can show it at once; the secret decides.
    """

    image = qrcode.make(
        f"{PASS_PREFIX}{reference}:{pass_secret}",
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
    )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def pass_qr_data_url(pass_secret: str, reference: str) -> str:
    """The same QR as an image the registration page can display."""

    return "data:image/png;base64," + base64.b64encode(pass_qr_png(pass_secret, reference)).decode("ascii")


def site_for_key(database: Session, key: str) -> Site:
    """Find the active site a QR link belongs to."""

    wanted = key.strip().lower()
    for site in database.scalars(select(Site).where(Site.is_active.is_(True))).all():
        if site_key(site) == wanted:
            return site
    raise WorkflowError(404, "This QR code does not belong to a site.")


def active_sites(database: Session) -> list[Site]:
    """Sites that can have a QR code."""

    return list(
        database.scalars(select(Site).where(Site.is_active.is_(True)).order_by(Site.name)).all()
    )


def _company_for(database: Session, name: str, site: Site) -> Company:
    existing = database.scalar(
        select(Company).where(func.lower(Company.name) == name.lower()).limit(1)
    )
    if existing is not None:
        return existing
    company = Company(
        id=uuid.uuid4(),
        seed_key=f"walkup-{uuid.uuid4().hex[:12]}",
        name=name,
        company_type="walk_up",
        country_code=site.country_code,
        is_active=True,
    )
    database.add(company)
    database.flush()
    return company


def _person_for(
    database: Session,
    *,
    first_name: str,
    last_name: str,
    email: str,
    population: Population,
    company: Company,
) -> Person:
    """Reuse an earlier walk-up person with the same name and email, else create one.

    Only people created through this flow are matched, so a walk-up registration can
    never attach itself to a person the site invited or seeded.
    """

    existing = database.scalar(
        select(Person).where(
            func.lower(Person.email) == email,
            func.lower(Person.first_name) == first_name.lower(),
            func.lower(Person.last_name) == last_name.lower(),
            Person.source_metadata["source"].as_string() == PERSON_SOURCE,
        )
    )
    if existing is not None:
        return existing
    person = Person(
        id=uuid.uuid4(),
        seed_key=f"walkup-{uuid.uuid4().hex[:16]}",
        company_id=company.id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        population=population,
        standing=PersonStanding.ACTIVE,
        source_metadata={"source": PERSON_SOURCE},
    )
    database.add(person)
    database.flush()
    return person


def _validated_arrival(
    database: Session, *, site_key_value: str, rules_version_id: uuid.UUID, confirmed: bool
) -> tuple[Site, LifeSavingRulesVersion]:
    """The checks every arrival passes before anything is stored."""

    if not confirmed:
        raise WorkflowError(422, "Tick the box to confirm that you read and understood the rules.")
    site = site_for_key(database, site_key_value)
    rules = database.get(LifeSavingRulesVersion, rules_version_id)
    if rules is None:
        raise WorkflowError(404, "Life-saving rules version not found.")
    if not rules.is_current:
        raise WorkflowError(
            409,
            "The life-saving rules have been updated. Reload the page to read the current version.",
        )
    return site, rules


# PUBLIC_INTERFACE
def register_walk_up(
    database: Session,
    *,
    site_key_value: str,
    first_name: str,
    last_name: str,
    company_name: str,
    email: str,
    population: str,
    rules_version_id: uuid.UUID,
    language: str,
    confirmed: bool,
    email_verified_at: datetime | None = None,
) -> tuple[
    WalkUpRegistration, Site, LifeSavingRulesVersion, LifeSavingRulesAcknowledgement, str
]:
    """Register an arrival and record the person's own life-saving confirmation.

    The last item returned is the pass secret for the person's QR code. It is shown
    once; only its hash is stored.

    Everything happens in one transaction: either the person is registered and has
    confirmed, or nothing is stored. The tick is required, and the rules the person
    saw must still be the ones in force.
    """

    site, rules = _validated_arrival(
        database,
        site_key_value=site_key_value,
        rules_version_id=rules_version_id,
        confirmed=confirmed,
    )

    email_key = email.strip().lower()
    company = _company_for(database, company_name, site)
    person = _person_for(
        database,
        first_name=first_name,
        last_name=last_name,
        email=email_key,
        population=Population(population),
        company=company,
    )

    chosen_language, translation = pick_translation(rules, language)
    acknowledgement = database.scalar(
        select(LifeSavingRulesAcknowledgement).where(
            LifeSavingRulesAcknowledgement.person_id == person.id,
            LifeSavingRulesAcknowledgement.rules_version_id == rules.id,
        )
    )
    now = _now()
    if acknowledgement is None:
        acknowledgement = LifeSavingRulesAcknowledgement(
            id=uuid.uuid4(),
            person_id=person.id,
            rules_version_id=rules.id,
            language=chosen_language,
            statement_text=translation["statement"],
            content_sha256=content_sha256(translation),
            acknowledged_at=now,
            method=CONFIRMATION_METHOD_WALK_UP,
            invitation_id=None,
        )
        database.add(acknowledgement)
        database.flush()
        append_audit_event(
            database,
            actor=None,
            action="life_saving_rules.acknowledged",
            entity_type="life_saving_rules_acknowledgement",
            entity_id=str(acknowledgement.id),
            reason="The person confirmed that they read and understood the life-saving rules.",
            details={
                "person_id": str(person.id),
                "rules_version": rules.version,
                "language": chosen_language,
                "method": CONFIRMATION_METHOD_WALK_UP,
                "content_sha256": acknowledgement.content_sha256,
            },
        )

    pass_secret = secrets.token_urlsafe(24)
    registration = WalkUpRegistration(
        id=uuid.uuid4(),
        site_id=site.id,
        person_id=person.id,
        acknowledgement_id=acknowledgement.id,
        registered_at=now,
        source="qr",
        pass_hash=_hash_pass(pass_secret),
        pass_expires_at=now + timedelta(hours=PASS_VALID_HOURS),
        email_verified_at=email_verified_at,
    )
    database.add(registration)
    database.flush()
    append_audit_event(
        database,
        actor=None,
        action="walk_up.registered",
        entity_type="walk_up_registration",
        entity_id=str(registration.id),
        reason="A person registered at the site entrance through the QR code.",
        details={
            "person_id": str(person.id),
            "site_id": str(site.id),
            "rules_version": rules.version,
            "method": CONFIRMATION_METHOD_WALK_UP,
            "email_verified": email_verified_at is not None,
        },
    )
    return registration, site, rules, acknowledgement, pass_secret


# PUBLIC_INTERFACE
def list_registrations(
    database: Session,
    *,
    since_hours: int,
    limit: int,
    site_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Recent arrivals, newest first, with who they are and what they confirmed."""

    cutoff = _now() - timedelta(hours=since_hours)
    query = (
        select(
            WalkUpRegistration,
            Person,
            Company,
            Site,
            LifeSavingRulesAcknowledgement,
            LifeSavingRulesVersion,
        )
        .join(Person, Person.id == WalkUpRegistration.person_id)
        .join(Company, Company.id == Person.company_id)
        .join(Site, Site.id == WalkUpRegistration.site_id)
        .join(
            LifeSavingRulesAcknowledgement,
            LifeSavingRulesAcknowledgement.id == WalkUpRegistration.acknowledgement_id,
        )
        .join(
            LifeSavingRulesVersion,
            LifeSavingRulesVersion.id == LifeSavingRulesAcknowledgement.rules_version_id,
        )
        .where(WalkUpRegistration.registered_at >= cutoff)
        .order_by(WalkUpRegistration.registered_at.desc())
        .limit(limit)
    )
    if site_id is not None:
        query = query.where(WalkUpRegistration.site_id == site_id)
    refused = {
        entity_id: (count, last)
        for entity_id, count, last in database.execute(
            select(AuditEvent.entity_id, func.count(), func.max(AuditEvent.occurred_at))
            .where(AuditEvent.action == "walk_up.refused")
            .group_by(AuditEvent.entity_id)
        ).all()
    }
    rows = []
    for registration, person, company, site, ack, rules in database.execute(query).all():
        rows.append(
            {
                "id": registration.id,
                "reference": reference_for(registration.id),
                "person_id": person.id,
                "first_name": person.first_name,
                "last_name": person.last_name,
                "company_name": company.name,
                "email": person.email,
                "population": person.population.value,
                "site_name": site.name,
                "registered_at": registration.registered_at,
                "rules_version": rules.version,
                "language": ack.language,
                "statement_text": ack.statement_text,
                "admitted_at": registration.admitted_at,
                "exited_at": registration.exited_at,
                "email_verified": registration.email_verified_at is not None,
                "refusal_count": refused.get(str(registration.id), (0, None))[0],
                "last_refused_at": refused.get(str(registration.id), (0, None))[1],
            }
        )
    return rows


def _find_registration(
    database: Session, *, site: Site, code: str
) -> WalkUpRegistration:
    """Find a recent registration at this site from its QR secret or its short reference."""

    cleaned = code.strip()
    if cleaned.lower().startswith(PASS_PREFIX):
        cleaned = cleaned[len(PASS_PREFIX):]
        # Current QR codes read "<reference>:<secret>"; earlier ones hold the secret alone.
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1]
    cutoff = _now() - timedelta(hours=PASS_VALID_HOURS)
    query = select(WalkUpRegistration).where(
        WalkUpRegistration.site_id == site.id, WalkUpRegistration.registered_at >= cutoff
    )
    if re.fullmatch(r"[0-9A-Fa-f]{8}", cleaned):
        matches = list(
            database.scalars(
                query.where(cast(WalkUpRegistration.id, String).startswith(cleaned.lower()))
            ).all()
        )
        if len(matches) > 1:
            raise WorkflowError(409, "More than one registration has that code. Scan the QR code instead.")
    else:
        matches = list(
            database.scalars(query.where(WalkUpRegistration.pass_hash == _hash_pass(cleaned))).all()
        )
    if not matches:
        raise WorkflowError(
            404,
            "No recent registration matches this code. It may have expired; the person can register again.",
        )
    return matches[0]


def _entry_state(database: Session, registration: WalkUpRegistration) -> dict[str, Any]:
    """Decide, from the records now, whether this person may be let in."""

    person = database.get(Person, registration.person_id)
    company = database.get(Company, person.company_id)
    site = database.get(Site, registration.site_id)
    now = _now()
    summary = status_for_people(database, [person.id])[person.id]
    reasons: list[dict[str, str]] = []
    if summary["status"] == "outdated":
        reasons.append(
            {
                "code": "LIFE_SAVING_RULES_OUTDATED",
                "message": f"The rules changed to version {summary['current_rules_version']} after they confirmed. They must register again.",
            }
        )
    elif summary["status"] != "confirmed":
        reasons.append(
            {
                "code": "LIFE_SAVING_RULES_NOT_CONFIRMED",
                "message": "They have not confirmed that they read and understood the life-saving rules.",
            }
        )
    if person.standing != PersonStanding.ACTIVE:
        reasons.append({"code": "PERSON_NOT_ACTIVE", "message": "This person is not allowed on site."})
    if _is_blacklisted(database, person=person, evaluated_at=now):
        reasons.append({"code": "BLACKLISTED", "message": "This person or their company is blacklisted."})
    if registration.exited_at is not None:
        reasons.append(
            {
                "code": "ALREADY_LEFT",
                "message": "They have already left. They must register again to come back in.",
            }
        )
    admitted_by = None
    if registration.admitted_by_id is not None:
        operator = database.get(UserAccount, registration.admitted_by_id)
        admitted_by = operator.display_name if operator else None
    refusals = _refusal_summary(database, registration.id)
    return {
        "registration_id": registration.id,
        "reference": reference_for(registration.id),
        "first_name": person.first_name,
        "last_name": person.last_name,
        "company_name": company.name,
        "population": person.population.value,
        "site_name": site.name,
        "registered_at": registration.registered_at,
        "rules_version": summary["confirmed_rules_version"],
        "rules_language": summary["language"],
        "eligible": not reasons,
        "reasons": reasons,
        "admitted_at": registration.admitted_at,
        "admitted_by": admitted_by,
        "email_verified": registration.email_verified_at is not None,
        "exited_at": registration.exited_at,
        "refusal_count": refusals[0],
        "last_refused_at": refusals[1],
    }


def _refusal_summary(database: Session, registration_id: uuid.UUID) -> tuple[int, datetime | None]:
    """How many times this arrival was refused, and when last."""

    row = database.execute(
        select(func.count(), func.max(AuditEvent.occurred_at)).where(
            AuditEvent.action == "walk_up.refused", AuditEvent.entity_id == str(registration_id)
        )
    ).one()
    return int(row[0] or 0), row[1]


def _record_refusal(
    database: Session,
    *,
    actor: UserAccount,
    registration: WalkUpRegistration,
    source: str,
    reasons: list[str],
    note: str = "",
) -> bool:
    """Write the refusal to the audit trail. Returns False if it was a recent repeat.

    ``source`` is ``"system"`` when the records say the person may not enter, and
    ``"officer"`` when the officer turns away someone the records would allow in.
    """

    now = _now()
    if source == "system":
        repeat = database.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "walk_up.refused",
                AuditEvent.entity_id == str(registration.id),
                AuditEvent.actor_id == actor.id,
                AuditEvent.details["source"].as_string() == "system",
                AuditEvent.occurred_at >= now - timedelta(seconds=REFUSAL_DEDUPE_SECONDS),
            )
        )
        if repeat:
            return False
    append_audit_event(
        database,
        actor=actor,
        action="walk_up.refused",
        entity_type="walk_up_registration",
        entity_id=str(registration.id),
        reason=(
            "The records do not allow this walk-up person in."
            if source == "system"
            else "A gate operator turned this walk-up person away."
        ),
        details={
            "person_id": str(registration.person_id),
            "site_id": str(registration.site_id),
            "registration_id": str(registration.id),
            "source": source,
            "reasons": reasons,
            **({"note": note} if note else {}),
        },
    )
    return True


def _record_lookup(
    database: Session,
    *,
    actor: UserAccount,
    registration: WalkUpRegistration,
    method: str,
) -> bool:
    """Write that the officer checked this person at the kiosk and the person may enter.

    ``method`` says how the code was read ("qr" or "reference"); the code itself is never
    stored. A repeated check by the same officer within a minute is not recorded again.
    """

    now = _now()
    repeat = database.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "walk_up.looked_up",
            AuditEvent.entity_id == str(registration.id),
            AuditEvent.actor_id == actor.id,
            AuditEvent.occurred_at >= now - timedelta(seconds=LOOKUP_DEDUPE_SECONDS),
        )
    )
    if repeat:
        return False
    append_audit_event(
        database,
        actor=actor,
        action="walk_up.looked_up",
        entity_type="walk_up_registration",
        entity_id=str(registration.id),
        reason="A gate operator checked a walk-up registration at the kiosk.",
        details={
            "person_id": str(registration.person_id),
            "site_id": str(registration.site_id),
            "registration_id": str(registration.id),
            "method": method,
            "result": "may_enter",
            "already_admitted": registration.admitted_at is not None,
        },
    )
    return True


# PUBLIC_INTERFACE
def lookup_for_gate(
    database: Session, *, actor: UserAccount, site_key_value: str, code: str
) -> dict[str, Any]:
    """Show the operator who a scanned or typed code belongs to, and whether they may enter.

    Looking someone up changes nothing about the person, but every check is recorded in
    the audit trail: a lookup (the person may enter), a refusal (the records do not allow
    entry), or a code that matches no recent registration.
    """

    site = site_for_key(database, site_key_value)
    try:
        registration = _find_registration(database, site=site, code=code)
    except WorkflowError as error:
        if error.status_code == 404:
            cleaned = code.strip()
            kind = "reference" if re.fullmatch(r"[0-9A-Fa-f]{8}", cleaned) else "qr"
            # Never store the code itself: it may be the QR secret.
            append_audit_event(
                database,
                actor=actor,
                action="walk_up.lookup_failed",
                entity_type="site",
                entity_id=str(site.id),
                reason="A code shown at the kiosk matched no recent walk-up registration.",
                details={"site_id": str(site.id), "code_kind": kind, "source": "system"},
            )
            database.commit()
        raise
    state = _entry_state(database, registration)
    if not state["eligible"] and registration.admitted_at is None:
        if _record_refusal(
            database,
            actor=actor,
            registration=registration,
            source="system",
            reasons=[reason["code"] for reason in state["reasons"]],
        ):
            state = _entry_state(database, registration)
    elif state["eligible"]:
        stripped = code.strip()
        method = "reference" if re.fullmatch(r"[0-9A-Fa-f]{8}", stripped) else "qr"
        _record_lookup(database, actor=actor, registration=registration, method=method)
    return state


# PUBLIC_INTERFACE
def refuse_at_gate(
    database: Session,
    *,
    actor: UserAccount,
    site_key_value: str,
    registration_id: uuid.UUID,
    reason: str,
    note: str = "",
) -> dict[str, Any]:
    """Record that the officer turned this person away, with the reason they chose."""

    if reason not in OFFICER_REFUSAL_REASONS:
        raise WorkflowError(422, "Choose a reason for refusing entry.")
    cleaned = " ".join(note.split())[:200]
    if reason == "other" and not cleaned:
        raise WorkflowError(422, "Write a short note when the reason is other.")
    site = site_for_key(database, site_key_value)
    registration = database.scalar(
        select(WalkUpRegistration).where(
            WalkUpRegistration.id == registration_id, WalkUpRegistration.site_id == site.id
        )
    )
    if registration is None:
        raise WorkflowError(404, "No registration found.")
    if registration.admitted_at is not None:
        raise WorkflowError(409, "This person was already let in, so entry cannot be refused.")
    _record_refusal(
        database,
        actor=actor,
        registration=registration,
        source="officer",
        reasons=[reason],
        note=cleaned,
    )
    return _entry_state(database, registration)


# PUBLIC_INTERFACE
def admit_at_gate(
    database: Session,
    *,
    actor: UserAccount,
    site_key_value: str,
    registration_id: uuid.UUID,
) -> dict[str, Any]:
    """Record that the operator let this person in, if the records still allow it.

    The decision is made here from the records, not taken from the screen. Letting
    the same person in twice returns the first entry and writes nothing new.
    """

    site = site_for_key(database, site_key_value)
    registration = database.scalar(
        select(WalkUpRegistration)
        .where(WalkUpRegistration.id == registration_id, WalkUpRegistration.site_id == site.id)
        .with_for_update()
    )
    if registration is None or registration.registered_at < _now() - timedelta(hours=PASS_VALID_HOURS):
        raise WorkflowError(404, "No recent registration found. The person can register again.")
    if registration.exited_at is not None:
        # Recorded and committed here, because the caller rolls back when this raises.
        _record_refusal(database, actor=actor, registration=registration, source="system", reasons=["ALREADY_LEFT"])
        database.commit()
        raise WorkflowError(409, "They have already left. They must register again to come back in.")
    if registration.admitted_at is not None:
        return _entry_state(database, registration)
    state = _entry_state(database, registration)
    if not state["eligible"]:
        _record_refusal(
            database,
            actor=actor,
            registration=registration,
            source="system",
            reasons=[reason["code"] for reason in state["reasons"]],
        )
        database.commit()
        raise WorkflowError(409, state["reasons"][0]["message"])
    registration.admitted_at = _now()
    registration.admitted_by_id = actor.id
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="walk_up.admitted",
        entity_type="walk_up_registration",
        entity_id=str(registration.id),
        reason="A gate operator let a walk-up registrant in at the kiosk.",
        details={
            "person_id": str(registration.person_id),
            "site_id": str(site.id),
            "registration_id": str(registration.id),
        },
    )
    return _entry_state(database, registration)


# --- the email check ----------------------------------------------------------


def _code_hash(pending_id: uuid.UUID, code: str) -> str:
    return hashlib.sha256(f"{pending_id}:{code}".encode("utf-8")).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def email_hint(email: str) -> str:
    """Show enough of the address for the person to recognise it, no more."""

    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


# PUBLIC_INTERFACE
def start_email_check(
    database: Session,
    *,
    site_key_value: str,
    first_name: str,
    last_name: str,
    company_name: str,
    email: str,
    population: str,
    rules_version_id: uuid.UUID,
    language: str,
    confirmed: bool,
) -> tuple[WalkUpPending, str, Site]:
    """Hold a registration until its email code is entered. Stores no person yet.

    Returns the pending record, the plain code to email (never stored) and the site.
    """

    site, _rules = _validated_arrival(
        database,
        site_key_value=site_key_value,
        rules_version_id=rules_version_id,
        confirmed=confirmed,
    )
    now = _now()
    database.execute(delete(WalkUpPending).where(WalkUpPending.created_at < now - timedelta(hours=1)))
    email_key = email.strip().lower()
    recent = database.scalar(
        select(func.count())
        .select_from(WalkUpPending)
        .where(WalkUpPending.email == email_key, WalkUpPending.created_at >= now - timedelta(hours=1))
    )
    if (recent or 0) >= MAX_CODES_PER_EMAIL_PER_HOUR:
        raise WorkflowError(429, "Too many codes have been requested for this email address. Try again later.")
    pending_id = uuid.uuid4()
    code = _new_code()
    pending = WalkUpPending(
        id=pending_id,
        site_id=site.id,
        first_name=first_name,
        last_name=last_name,
        company_name=company_name,
        email=email_key,
        population=population,
        rules_version_id=rules_version_id,
        language=language,
        code_hash=_code_hash(pending_id, code),
        code_expires_at=now + timedelta(minutes=CODE_VALID_MINUTES),
        attempts=0,
        sends=1,
        last_sent_at=now,
        created_at=now,
    )
    database.add(pending)
    database.flush()
    return pending, code, site


# PUBLIC_INTERFACE
def resend_email_code(database: Session, *, pending_id: uuid.UUID) -> tuple[WalkUpPending, str, Site]:
    """Send a fresh code for a pending registration, within the resend limits."""

    pending = database.scalar(
        select(WalkUpPending).where(WalkUpPending.id == pending_id).with_for_update()
    )
    now = _now()
    if pending is None or pending.created_at < now - timedelta(hours=1):
        raise WorkflowError(404, "This registration has expired. Please register again.")
    if pending.sends >= MAX_CODE_SENDS:
        raise WorkflowError(429, "No more codes can be sent for this registration. Please register again.")
    if (now - pending.last_sent_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
        raise WorkflowError(429, "Wait a few seconds before asking for another code.")
    code = _new_code()
    pending.code_hash = _code_hash(pending.id, code)
    pending.code_expires_at = now + timedelta(minutes=CODE_VALID_MINUTES)
    pending.attempts = 0
    pending.sends += 1
    pending.last_sent_at = now
    database.flush()
    return pending, code, database.get(Site, pending.site_id)


# PUBLIC_INTERFACE
def verify_email_code(
    database: Session, *, pending_id: uuid.UUID, code: str
) -> tuple[WalkUpRegistration, Site, LifeSavingRulesVersion, LifeSavingRulesAcknowledgement, str]:
    """Check the code and, if it is right, complete the registration.

    A wrong code counts against a small limit. That count is saved even though the
    request fails, so the limit cannot be got around by retrying.
    """

    pending = database.scalar(
        select(WalkUpPending).where(WalkUpPending.id == pending_id).with_for_update()
    )
    now = _now()
    if pending is None:
        raise WorkflowError(404, "This registration has expired. Please register again.")
    if pending.code_expires_at < now:
        database.delete(pending)
        database.commit()
        raise WorkflowError(410, "That code has expired. Please register again.")
    if pending.attempts >= MAX_CODE_ATTEMPTS:
        database.delete(pending)
        database.commit()
        raise WorkflowError(429, "Too many wrong codes. Please register again.")
    if not secrets.compare_digest(pending.code_hash, _code_hash(pending.id, code.strip())):
        pending.attempts += 1
        left = MAX_CODE_ATTEMPTS - pending.attempts
        if left <= 0:
            database.delete(pending)
            message = "Too many wrong codes. Please register again."
            status_code = 429
        else:
            message = f"That code is not right. {left} {'try' if left == 1 else 'tries'} left."
            status_code = 422
        database.commit()
        raise WorkflowError(status_code, message)

    result = register_walk_up(
        database,
        site_key_value=site_key(database.get(Site, pending.site_id)),
        first_name=pending.first_name,
        last_name=pending.last_name,
        company_name=pending.company_name,
        email=pending.email,
        population=pending.population,
        rules_version_id=pending.rules_version_id,
        language=pending.language,
        confirmed=True,
        email_verified_at=now,
    )
    database.delete(pending)
    database.flush()
    return result


# --- who is on site -----------------------------------------------------------


# PUBLIC_INTERFACE
def record_exit(
    database: Session,
    *,
    actor: UserAccount,
    site_key_value: str,
    registration_id: uuid.UUID,
) -> dict[str, Any]:
    """Record that a person who was let in has now left. Repeating it changes nothing."""

    site = site_for_key(database, site_key_value)
    registration = database.scalar(
        select(WalkUpRegistration)
        .where(WalkUpRegistration.id == registration_id, WalkUpRegistration.site_id == site.id)
        .with_for_update()
    )
    if registration is None:
        raise WorkflowError(404, "No registration found.")
    if registration.admitted_at is None:
        raise WorkflowError(409, "This person was never let in, so there is no exit to record.")
    if registration.exited_at is not None:
        return _entry_state(database, registration)
    registration.exited_at = _now()
    registration.exited_by_id = actor.id
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="walk_up.exited",
        entity_type="walk_up_registration",
        entity_id=str(registration.id),
        reason="A walk-up registrant left the site.",
        details={
            "person_id": str(registration.person_id),
            "site_id": str(site.id),
            "registration_id": str(registration.id),
        },
    )
    return _entry_state(database, registration)


# PUBLIC_INTERFACE
def list_on_site(database: Session, *, site_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Walk-up people who were let in and have not left, longest on site first."""

    query = (
        select(WalkUpRegistration, Person, Company, Site)
        .join(Person, Person.id == WalkUpRegistration.person_id)
        .join(Company, Company.id == Person.company_id)
        .join(Site, Site.id == WalkUpRegistration.site_id)
        .where(WalkUpRegistration.admitted_at.is_not(None), WalkUpRegistration.exited_at.is_(None))
        .order_by(WalkUpRegistration.admitted_at)
    )
    if site_id is not None:
        query = query.where(WalkUpRegistration.site_id == site_id)
    stale_before = _now() - timedelta(hours=STALE_ON_SITE_HOURS)
    rows = []
    for registration, person, company, site in database.execute(query).all():
        operator = (
            database.get(UserAccount, registration.admitted_by_id) if registration.admitted_by_id else None
        )
        rows.append(
            {
                "registration_id": registration.id,
                "reference": reference_for(registration.id),
                "person_id": person.id,
                "first_name": person.first_name,
                "last_name": person.last_name,
                "company_name": company.name,
                "population": person.population.value,
                "site_name": site.name,
                "site_key": site_key(site),
                "admitted_at": registration.admitted_at,
                "admitted_by": operator.display_name if operator else None,
                "stale": registration.admitted_at < stale_before,
            }
        )
    return rows


# --- the shared dashboard -----------------------------------------------------


# PUBLIC_INTERFACE
def walk_up_presence_rows(database: Session, *, site_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Walk-up people on site now, shaped like the roster rows of invited visitors.

    The main dashboard shows both kinds in one roster. Only the shared dashboard and
    the presence API use this. The presence list the expiry features read is not
    changed, because a walk-up person has no visit.
    """

    rows = []
    for row in list_on_site(database, site_id=site_id):
        registration = database.get(WalkUpRegistration, row["registration_id"])
        rows.append(
            {
                "gate_event_id": None,
                "presence_event_id": None,
                "person_id": row["person_id"],
                "person_name": f"{row['first_name']} {row['last_name']}",
                "population": row["population"],
                "id_expiry_date": None,
                "visit_id": None,
                "site_id": registration.site_id,
                "site_name": row["site_name"],
                "site_key": row["site_key"],
                "entered_at": row["admitted_at"],
                "visit_ends_at": None,
                "decision": GateDecision.GRANT.value,
                "walk_up_registration_id": row["registration_id"],
                "source": "walk_up",
            }
        )
    return rows


# PUBLIC_INTERFACE
def walk_up_dashboard_activity(
    database: Session, *, window_started_at: datetime, as_of: datetime
) -> dict[str, Any]:
    """Walk-up entries, exits, grants and refusals inside the dashboard window.

    A let-in counts as a grant and an entry. A refusal (by the system or the officer)
    counts as a denial. An exit counts as an exit. Codes that matched nobody are not
    counted, because they are not a person.
    """

    counts: dict[uuid.UUID, dict[str, int]] = {}

    def bump(site: uuid.UUID, key: str) -> None:
        counts.setdefault(site, {"grants": 0, "denials": 0, "entries": 0, "exits": 0})[key] += 1

    decisions: list[dict[str, Any]] = []
    admitted = database.execute(
        select(WalkUpRegistration, Person, Site)
        .join(Person, Person.id == WalkUpRegistration.person_id)
        .join(Site, Site.id == WalkUpRegistration.site_id)
        .where(
            WalkUpRegistration.admitted_at.is_not(None),
            WalkUpRegistration.admitted_at >= window_started_at,
            WalkUpRegistration.admitted_at <= as_of,
        )
    ).all()
    for registration, person, site in admitted:
        bump(site.id, "grants")
        bump(site.id, "entries")
        decisions.append(
            {
                "gate_event_id": registration.id,
                "occurred_at": registration.admitted_at,
                "site_id": site.id,
                "site_name": site.name,
                "visit_id": None,
                "person_id": person.id,
                "person_name": f"{person.first_name} {person.last_name}",
                "decision": GateDecision.GRANT.value,
                "reason_codes": [],
                "source": "walk_up",
            }
        )
    for (site_id_value,) in database.execute(
        select(WalkUpRegistration.site_id).where(
            WalkUpRegistration.exited_at.is_not(None),
            WalkUpRegistration.exited_at >= window_started_at,
            WalkUpRegistration.exited_at <= as_of,
        )
    ).all():
        bump(site_id_value, "exits")

    refusals = database.scalars(
        select(AuditEvent).where(
            AuditEvent.action == "walk_up.refused",
            AuditEvent.occurred_at >= window_started_at,
            AuditEvent.occurred_at <= as_of,
        )
    ).all()
    people = {
        person.id: person
        for person in database.scalars(
            select(Person).where(
                Person.id.in_({uuid.UUID(e.details["person_id"]) for e in refusals if e.details.get("person_id")})
            )
        ).all()
    } if refusals else {}
    sites = {site.id: site for site in database.scalars(select(Site)).all()}
    for event in refusals:
        site = sites.get(uuid.UUID(event.details["site_id"])) if event.details.get("site_id") else None
        if site is None:
            continue
        person = people.get(uuid.UUID(event.details["person_id"])) if event.details.get("person_id") else None
        bump(site.id, "denials")
        decisions.append(
            {
                "gate_event_id": event.id,
                "occurred_at": event.occurred_at,
                "site_id": site.id,
                "site_name": site.name,
                "visit_id": None,
                "person_id": person.id if person else None,
                "person_name": f"{person.first_name} {person.last_name}" if person else None,
                "decision": GateDecision.DENY.value,
                "reason_codes": list(event.details.get("reasons", [])),
                "source": "walk_up",
            }
        )
    return {"counts": counts, "decisions": decisions}


# PUBLIC_INTERFACE
def merge_walk_ups_into_dashboard(
    database: Session, snapshot: dict[str, Any], *, recent_limit: int
) -> dict[str, Any]:
    """Add walk-up people and decisions to a dashboard snapshot, in place.

    "Currently present", "access grants", "access denials", entries, exits, the
    roster and the recent decisions then cover both invited and walk-up people.
    "Active visits" is unchanged, because a walk-up person has no visit. The invitation
    dashboard code itself is not touched: this runs on its finished result.
    """

    rows = walk_up_presence_rows(database)
    activity = walk_up_dashboard_activity(
        database,
        window_started_at=snapshot["activity_window_started_at"],
        as_of=snapshot["as_of"],
    )
    by_site = {site["site_id"]: site for site in snapshot["sites"]}
    totals = snapshot["totals"]
    for row in rows:
        site = by_site.get(row["site_id"])
        if site is not None:
            site["present_count"] += 1
            totals["present_count"] += 1
    for site_id_value, counts in activity["counts"].items():
        site = by_site.get(site_id_value)
        if site is None:
            continue
        for site_key_name, total_key, count_key in (
            ("grant_count", "grant_count", "grants"),
            ("denial_count", "denial_count", "denials"),
            ("entry_count", "entry_count", "entries"),
            ("exit_count", "exit_count", "exits"),
        ):
            site[site_key_name] += counts[count_key]
            totals[total_key] += counts[count_key]
    snapshot["current_presence"] = sorted(
        list(snapshot["current_presence"]) + rows,
        key=lambda row: (row["site_name"], row["person_name"]),
    )
    snapshot["recent_decisions"] = sorted(
        list(snapshot["recent_decisions"]) + activity["decisions"],
        key=lambda decision: decision["occurred_at"],
        reverse=True,
    )[:recent_limit]
    return snapshot
