"""Life-saving rules: what a person is shown, and the record that they confirmed it.

A contractor must confirm, personally, that they have read and understood the
life-saving rules before entering site, and the site must be able to see that
they did. This module owns the confirmation record and the rule for what counts
as confirmed. Approval and the gate both read it through the compliance check,
so neither can let someone through who has not confirmed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ComplianceRequirement,
    LifeSavingRulesAcknowledgement,
    LifeSavingRulesVersion,
)
from app.services.audit import append_audit_event
from app.services.workflows import WorkflowError, get_invitee_registration

CONFIRMATION_METHOD_INVITEE_LINK = "invitee_registration_link"
_FALLBACK_LANGUAGE = "en"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def content_sha256(translation: dict[str, Any]) -> str:
    """Hash exactly what a person was shown, so the record stays meaningful later."""

    canonical = json.dumps(translation, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _translations(rules: LifeSavingRulesVersion) -> dict[str, dict[str, Any]]:
    translations = rules.content.get("translations", {})
    return translations if isinstance(translations, dict) else {}


def pick_translation(
    rules: LifeSavingRulesVersion, language: str | None
) -> tuple[str, dict[str, Any]]:
    """Return the requested language, else its base language, else English, else any."""

    translations = _translations(rules)
    if not translations:
        raise WorkflowError(409, "The life-saving rules have no published text.")
    wanted = (language or _FALLBACK_LANGUAGE).lower()
    for candidate in (wanted, wanted.split("-")[0], _FALLBACK_LANGUAGE):
        if candidate in translations:
            return candidate, translations[candidate]
    first = sorted(translations)[0]
    return first, translations[first]


def get_current_rules(database: Session) -> LifeSavingRulesVersion:
    """Return the rules in force now."""

    rules = database.scalar(
        select(LifeSavingRulesVersion).where(LifeSavingRulesVersion.is_current.is_(True))
    )
    if rules is None:
        raise WorkflowError(404, "No life-saving rules have been published.")
    return rules


def rules_for_display(rules: LifeSavingRulesVersion, language: str | None) -> dict[str, Any]:
    """Shape the current rules for the person who is about to confirm them."""

    chosen, translation = pick_translation(rules, language)
    return {
        "id": rules.id,
        "version": rules.version,
        "language": chosen,
        "available_languages": sorted(_translations(rules)),
        "title": translation["title"],
        "intro": translation["intro"],
        "rules": translation["rules"],
        "statement": translation["statement"],
        "is_sample": bool(rules.content.get("is_sample", False)),
    }


def _format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def status_for_people(
    database: Session, person_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Return each person's confirmation status against the rules in force now.

    ``confirmed``     confirmed the current version.
    ``outdated``      confirmed an earlier version only; must confirm the new one.
    ``not_confirmed`` has never confirmed.
    """

    current = database.scalar(
        select(LifeSavingRulesVersion).where(LifeSavingRulesVersion.is_current.is_(True))
    )
    versions = {
        row.id: row.version for row in database.scalars(select(LifeSavingRulesVersion)).all()
    }
    by_person: dict[uuid.UUID, list[LifeSavingRulesAcknowledgement]] = {}
    if person_ids:
        for ack in database.scalars(
            select(LifeSavingRulesAcknowledgement)
            .where(LifeSavingRulesAcknowledgement.person_id.in_(person_ids))
            .order_by(LifeSavingRulesAcknowledgement.acknowledged_at.desc())
        ).all():
            by_person.setdefault(ack.person_id, []).append(ack)

    result: dict[uuid.UUID, dict[str, Any]] = {}
    for person_id in person_ids:
        acks = by_person.get(person_id, [])
        matching = next((a for a in acks if current is not None and a.rules_version_id == current.id), None)
        chosen = matching or (acks[0] if acks else None)
        if matching is not None:
            status = "confirmed"
        elif chosen is not None:
            status = "outdated"
        else:
            status = "not_confirmed"
        result[person_id] = {
            "status": status,
            "current_rules_version": current.version if current else None,
            "confirmed_rules_version": versions.get(chosen.rules_version_id) if chosen else None,
            "language": chosen.language if chosen else None,
            "acknowledged_at": chosen.acknowledged_at if chosen else None,
            "method": chosen.method if chosen else None,
        }
    return result


def invitee_confirmation(database: Session, invitation: Any) -> tuple[bool, datetime | None]:
    """Whether the person behind a registration link has confirmed the rules now in force."""

    if invitation.person_id is None:
        return False, None
    summary = status_for_people(database, [invitation.person_id])[invitation.person_id]
    if summary["status"] == "confirmed":
        return True, summary["acknowledged_at"]
    return False, None


def history_for_person(database: Session, person_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return every recorded confirmation for one person, newest first."""

    versions = {
        row.id: row.version for row in database.scalars(select(LifeSavingRulesVersion)).all()
    }
    acks = database.scalars(
        select(LifeSavingRulesAcknowledgement)
        .where(LifeSavingRulesAcknowledgement.person_id == person_id)
        .order_by(LifeSavingRulesAcknowledgement.acknowledged_at.desc())
    ).all()
    return [
        {
            "id": ack.id,
            "rules_version": versions.get(ack.rules_version_id, 0),
            "language": ack.language,
            "statement_text": ack.statement_text,
            "acknowledged_at": ack.acknowledged_at,
            "method": ack.method,
        }
        for ack in acks
    ]


def life_saving_check(
    database: Session,
    *,
    person_id: uuid.UUID,
    requirement: ComplianceRequirement,
) -> dict[str, Any]:
    """Resolve the life-saving requirement into the typed check used at approval and the gate.

    Fails closed: if the rules have not been published, nobody can pass.
    """

    summary = status_for_people(database, [person_id])[person_id]
    if summary["current_rules_version"] is None:
        status = "missing"
        detail = "No life-saving rules have been published, so they cannot be confirmed."
    elif summary["status"] == "confirmed":
        status = "passed"
        detail = (
            f"Confirmed read and understood on {_format_utc(summary['acknowledged_at'])} "
            f"(rules version {summary['confirmed_rules_version']})."
        )
    elif summary["status"] == "outdated":
        status = "expired"
        detail = (
            f"Confirmed version {summary['confirmed_rules_version']} on "
            f"{_format_utc(summary['acknowledged_at'])}, but version "
            f"{summary['current_rules_version']} is now in force and must be confirmed."
        )
    else:
        status = "missing"
        detail = "The person has not confirmed that they read and understood the life-saving rules."

    return {
        "code": requirement.code,
        "label": requirement.label,
        "kind": requirement.requirement_kind.value,
        "status": status,
        "blocking": requirement.is_blocking and status != "passed",
        "detail": detail,
        "requirement_id": str(requirement.id),
    }


# PUBLIC_INTERFACE
def confirm_rules_by_invitee(
    database: Session,
    *,
    token: str,
    rules_version_id: uuid.UUID,
    language: str,
    confirmed: bool,
) -> LifeSavingRulesAcknowledgement:
    """Record the contractor's own confirmation, made with their registration link.

    Only the holder of the link can confirm, and only for the person that link
    registered. Staff cannot confirm on someone's behalf: the point of the record
    is that the contractor did it themselves. Confirming the same version twice
    returns the first record and writes nothing new.
    """

    invitation = get_invitee_registration(database, token=token, lock=True)
    if invitation.person_id is None or invitation.registration_completed_at is None:
        raise WorkflowError(409, "Complete your registration before confirming the life-saving rules.")
    if not confirmed:
        raise WorkflowError(422, "Tick the box to confirm that you read and understood the rules.")

    rules = database.get(LifeSavingRulesVersion, rules_version_id)
    if rules is None:
        raise WorkflowError(404, "Life-saving rules version not found.")
    if not rules.is_current:
        raise WorkflowError(409, "The life-saving rules have been updated. Reload the page to read the current version.")

    existing = database.scalar(
        select(LifeSavingRulesAcknowledgement).where(
            LifeSavingRulesAcknowledgement.person_id == invitation.person_id,
            LifeSavingRulesAcknowledgement.rules_version_id == rules.id,
        )
    )
    if existing is not None:
        return existing

    chosen_language, translation = pick_translation(rules, language)
    acknowledgement = LifeSavingRulesAcknowledgement(
        id=uuid.uuid4(),
        person_id=invitation.person_id,
        rules_version_id=rules.id,
        language=chosen_language,
        statement_text=translation["statement"],
        content_sha256=content_sha256(translation),
        acknowledged_at=_now(),
        method=CONFIRMATION_METHOD_INVITEE_LINK,
        invitation_id=invitation.id,
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
            "person_id": str(invitation.person_id),
            "rules_version": rules.version,
            "language": chosen_language,
            "method": CONFIRMATION_METHOD_INVITEE_LINK,
            "content_sha256": acknowledgement.content_sha256,
        },
    )
    return acknowledgement
