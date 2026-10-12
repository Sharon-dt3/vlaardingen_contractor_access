"""Authoritative Batch 4 identity and gate-decision commands."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccessToken,
    AccessTokenStatus,
    Company,
    Evidence,
    GateDecision,
    GateEvent,
    IdentityVerification,
    Invitation,
    Person,
    PersonStanding,
    Site,
    UserAccount,
    Visit,
    VisitStatus,
)
from app.providers import get_identity_verification_provider
from app.services.audit import append_audit_event
from app.services.batch3 import (
    _active_approval,
    _identity_check,
    _is_blacklisted,
    _now,
    _requirement_checks,
)
from app.services.batch5 import record_gate_entry
from app.services.batch6 import current_demo_time
from app.services.workflows import WorkflowError
from app.providers import StorageProvider

_GATE_CHECK_PRECEDENCE = {
    "TOKEN": 10,
    "SITE": 20,
    "VISIT": 30,
    "INVITATION": 35,
    "VISIT_WINDOW": 40,
    "VISIT_STATUS": 50,
    "PERSON_STANDING": 60,
    "BLACKLIST": 70,
    "APPROVAL": 90,
    "IDENTITY": 110,
    "PHYSICAL_DOCUMENT_COMPARISON": 120,
}
_COMPLIANCE_CHECK_PRECEDENCE = 80


def _token_current(token: AccessToken, evaluated_at: datetime) -> bool:
    """Active, not past its exit time, and past its entry time if one was set."""

    return (
        token.status is AccessTokenStatus.ACTIVE
        and token.expires_at > evaluated_at
        and (token.valid_from is None or token.valid_from <= evaluated_at)
    )


def _check(
    *,
    code: str,
    label: str,
    passed: bool,
    reason_code: str | None,
    detail: str,
    corrective_action: str | None,
) -> dict[str, Any]:
    """Build one consistently typed, ordered gate-decision check."""

    return {
        "code": code,
        "label": label,
        "status": "passed" if passed else "failed",
        "blocking": not passed,
        "reason_code": None if passed else reason_code,
        "detail": detail,
        "corrective_action": None if passed else corrective_action,
    }


def _check_precedence(check: dict[str, Any]) -> tuple[int, str]:
    """Return the stable denial-precedence position for one gate check."""

    code = str(check["code"])
    return (
        _GATE_CHECK_PRECEDENCE.get(code, _COMPLIANCE_CHECK_PRECEDENCE),
        code,
    )


def _ordered_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order gate checks so the first blocking failure is always authoritative."""

    return sorted(checks, key=_check_precedence)


def _decision_outcome(
    checks: list[dict[str, Any]],
) -> tuple[GateDecision, list[str], list[str], list[str]]:
    """Return a single actionable outcome using the required gate precedence.

    Every evaluated check remains available to the operator.  A denial, however,
    records and returns only the highest-precedence blocking failure so the
    operator receives one unambiguous reason and next action.
    """

    failed_checks = [
        check
        for check in checks
        if check["blocking"] and check["status"] == "failed"
    ]
    if not failed_checks:
        return (
            GateDecision.GRANT,
            [],
            ["All mandatory server-side gate checks passed."],
            ["Record entry when the person passes the physical gate."],
        )

    primary_failure = failed_checks[0]
    reason_code = primary_failure["reason_code"] or "GATE_CHECK_FAILED"
    corrective_action = primary_failure["corrective_action"]
    return (
        GateDecision.DENY,
        [str(reason_code)],
        [str(primary_failure["detail"])],
        [str(corrective_action)] if corrective_action is not None else [],
    )


def _requirement_reason(check: dict[str, Any]) -> tuple[str, str]:
    """Translate an authoritative compliance check into gate-safe reason text."""

    code = str(check["code"])
    status = str(check["status"])
    if code == "LIFE_SAVING_RULES" and status == "missing":
        return (
            "LIFE_SAVING_RULES_NOT_CONFIRMED",
            "Ask the person to read and confirm the life-saving rules with their registration link, then evaluate again.",
        )
    if code == "LIFE_SAVING_RULES" and status == "expired":
        return (
            "LIFE_SAVING_RULES_OUTDATED",
            "The rules were updated. Ask the person to read and confirm the new version, then evaluate again.",
        )
    if code == "VLAARDINGEN_SITE_RULES" and status == "failed":
        return (
            "SITE_RULES_NOT_PASSED",
            "Complete the required site-rules training or contact the site manager.",
        )
    if code == "VLAARDINGEN_SITE_RULES" and status == "expired":
        return (
            "SITE_RULES_EXPIRED",
            "Renew the required site-rules training before attempting entry again.",
        )
    if code == "SHEQ_BASICS" and status == "failed":
        return (
            "SHEQ_NOT_PASSED",
            "Complete the required SHEQ training before attempting entry again.",
        )
    if code == "SHEQ_BASICS" and status == "expired":
        return (
            "SHEQ_EXPIRED",
            "Renew the required SHEQ training before attempting entry again.",
        )
    if code == "DRIVING_LICENCE" and status == "expired":
        return (
            "DRIVING_LICENCE_EXPIRED",
            "Renew and verify the driving-licence evidence before attempting entry again.",
        )
    return (
        f"{code}_{status.upper()}",
        "Resolve the required evidence or training item and request a new evaluation.",
    )


def _identity_snapshot(
    *,
    person: Person,
    presentation_reference: str,
) -> dict[str, Any]:
    """Return a sanitized identity result without exposing biometric information."""

    try:
        result = get_identity_verification_provider().verify(
            person=person,
            presentation_reference=presentation_reference,
        )
        return {
            "match": result.is_match,
            "confidence": result.confidence,
            "mode": result.mode,
            "provider_reference": result.provider_reference,
            "evaluated_at": result.evaluated_at,
        }
    except RuntimeError:
        evaluated_at = _now()
        return {
            "match": False,
            "confidence": 0.0,
            "mode": "EXTERNAL",
            "provider_reference": "identity-provider-unavailable",
            "evaluated_at": evaluated_at,
        }


def _response(
    *,
    event: GateEvent,
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    """Serialize a persisted gate event into the stable Batch 4 response shape."""

    return {
        "gate_event_id": event.id,
        "decision": event.decision,
        "reason_codes": event.reason_codes,
        "reasons": event.reasons,
        "corrective_actions": event.corrective_actions,
        "primary_reason_code": (
            event.reason_codes[0]
            if event.reason_codes
            else "ACCESS_GRANTED"
        ),
        "primary_reason": event.reasons[0],
        "next_action": event.corrective_actions[0],
        "checks": event.checks,
        "identity": identity,
        "token_id": event.token_id,
        "visit_id": event.visit_id,
        "person_id": event.person_id,
        "requested_site_id": event.requested_site_id,
        "occurred_at": event.occurred_at,
    }


def _gate_presentation_records(
    database: Session, *, token_reference: str, requested_site_id: uuid.UUID
) -> tuple[Invitation, Person, Visit, Site]:
    """Resolve a current token exclusively on the server before exposing private data."""

    reference_hash = hashlib.sha256(token_reference.strip().encode("utf-8")).hexdigest()
    token = database.scalar(
        select(AccessToken).where(AccessToken.reference_hash == reference_hash)
    )
    now = current_demo_time(database) or _now()
    if token is None or token.status is not AccessTokenStatus.ACTIVE or token.expires_at <= now:
        raise WorkflowError(404, "The issued QR is unavailable or no longer active.")
    visit = database.get(Visit, token.visit_id)
    site = database.get(Site, requested_site_id)
    if visit is None or site is None or not site.is_active or visit.site_id != site.id:
        raise WorkflowError(404, "The issued QR is not valid at this gate site.")
    person = database.get(Person, visit.person_id)
    invitation = database.scalar(
        select(Invitation).where(Invitation.visit_id == visit.id)
    )
    if (
        person is None or invitation is None
        or invitation.person_id != person.id or invitation.site_id != site.id
        or invitation.response_status != "accepted"
    ):
        raise WorkflowError(404, "No accepted registered invitation is available for this QR.")
    return invitation, person, visit, site


# PUBLIC_INTERFACE
def get_gate_presentation(
    database: Session, *, token_reference: str, requested_site_id: uuid.UUID
) -> dict[str, Any]:
    """Return only the invitee and invitation uploads bound to a current issued QR."""

    invitation, person, visit, site = _gate_presentation_records(
        database, token_reference=token_reference, requested_site_id=requested_site_id
    )
    company = database.get(Company, person.company_id)
    uploads: list[dict[str, Any]] = []
    if invitation.identity_document_storage_reference:
        uploads.append({
            "id": None, "kind": "invitation_id", "label": "Invitation identity document",
            "filename": "Invitation ID",
            "media_type": invitation.identity_document_media_type or "application/octet-stream",
            "status": "uploaded",
        })
    records = database.scalars(
        select(Evidence)
        .where(Evidence.invitation_id == invitation.id, Evidence.person_id == person.id)
        .order_by(Evidence.created_at.desc(), Evidence.id)
    ).all()
    uploads.extend({
        "id": item.id, "kind": "evidence", "label": item.evidence_type.value.replace("_", " ").title(),
        "filename": item.filename, "media_type": item.media_type, "status": item.status.value,
    } for item in records)
    return {
        "invitation_id": invitation.id, "person_id": person.id,
        "person_name": f"{person.first_name} {person.last_name}",
        "email": person.email, "company_name": company.name if company else invitation.company_name,
        "population": person.population.value, "purpose": visit.purpose,
        "site_name": site.name, "starts_at": visit.starts_at, "ends_at": visit.ends_at,
        "uploads": uploads,
    }


# PUBLIC_INTERFACE
def read_gate_upload(
    database: Session, *, token_reference: str, requested_site_id: uuid.UUID,
    kind: str, evidence_id: uuid.UUID | None, storage: StorageProvider,
) -> tuple[str, bytes]:
    """Read only the private upload bound to the QR's accepted invitation."""

    invitation, person, _, _ = _gate_presentation_records(
        database, token_reference=token_reference, requested_site_id=requested_site_id
    )
    if kind == "invitation_id" and evidence_id is None:
        reference = invitation.identity_document_storage_reference
        media_type = invitation.identity_document_media_type
    elif kind == "evidence" and evidence_id is not None:
        evidence = database.get(Evidence, evidence_id)
        if evidence is None or evidence.invitation_id != invitation.id or evidence.person_id != person.id:
            raise WorkflowError(404, "This upload does not belong to the scanned invitation.")
        reference, media_type = evidence.storage_reference, evidence.media_type
    else:
        raise WorkflowError(404, "This upload does not belong to the scanned invitation.")
    if not reference or not media_type:
        raise WorkflowError(404, "The private upload is unavailable.")
    try:
        return media_type, storage.get(reference)
    except (FileNotFoundError, ValueError) as error:
        raise WorkflowError(404, "The private upload is unavailable.") from error


# PUBLIC_INTERFACE
def evaluate_gate_access(
    database: Session,
    *,
    actor: UserAccount,
    token_reference: str,
    requested_site_id: uuid.UUID,
    presentation_reference: str,
    comparison_confirmed: bool = False,
) -> dict[str, Any]:
    """Evaluate and persist one authoritative gate decision.

    The service always re-evaluates live token, site, visit window, person
    standing, blacklist, configured evidence and training, approval, and
    deterministic identity state, and requires the operator to confirm a
    physical-document comparison. Denial precedence is token, site, visit,
    standing, blacklist, compliance, approval, identity, then comparison.
    Frontend clients receive typed snapshots but cannot alter precedence or
    turn a denial into a grant.
    """

    # The saved demo clock governs eligibility; the gate event records when
    # this request actually happened on the server.
    occurred_at = _now()
    evaluated_at = current_demo_time(database) or occurred_at
    reference_hash = hashlib.sha256(token_reference.encode("utf-8")).hexdigest()
    token = database.scalar(
        select(AccessToken).where(AccessToken.reference_hash == reference_hash)
    )
    requested_site = database.get(Site, requested_site_id)

    if token is None:
        checks = [
            _check(
                code="TOKEN",
                label="Opaque access token",
                passed=False,
                reason_code="TOKEN_INVALID",
                detail="The presented access token is unknown.",
                corrective_action="Rescan the issued QR payload or request a new token.",
            )
        ]
        event = GateEvent(
            id=uuid.uuid4(),
            token_id=None,
            requested_site_id=requested_site_id,
            visit_id=None,
            person_id=None,
            operator_id=actor.id,
            scanned_reference_hash=reference_hash,
            decision=GateDecision.DENY,
            reason_codes=["TOKEN_INVALID"],
            reasons=["The presented access token is unknown."],
            corrective_actions=[
                "Rescan the issued QR payload or request a new token."
            ],
            checks=checks,
            identity_snapshot={},
            occurred_at=occurred_at,
        )
        database.add(event)
        database.flush()
        append_audit_event(
            database,
            actor=actor,
            action="gate.denied",
            entity_type="gate_event",
            entity_id=str(event.id),
            reason="Gate access was denied because the opaque token was invalid.",
            details={"reason_codes": event.reason_codes, "synthetic": True},
        )
        return _response(event=event, identity=None)

    visit = database.get(Visit, token.visit_id)
    person = database.get(Person, visit.person_id) if visit else None
    visit_site = database.get(Site, visit.site_id) if visit else None
    invitation = database.scalar(
        select(Invitation).where(Invitation.visit_id == visit.id)
    ) if visit else None
    checks: list[dict[str, Any]] = [
        _check(
            code="TOKEN",
            label="Opaque access token",
            passed=_token_current(token, evaluated_at),
            reason_code=(
                "TOKEN_EXPIRED"
                if token.expires_at <= evaluated_at
                else "TOKEN_NOT_YET_VALID"
                if token.valid_from is not None and token.valid_from > evaluated_at
                else "TOKEN_INACTIVE"
            ),
            detail=(
                "The opaque access token is active and current."
                if _token_current(token, evaluated_at)
                else "The opaque access token is not yet valid, expired, revoked, or inactive."
            ),
            corrective_action="Issue a new approved access token, or wait until its entry time.",
        ),
        _check(
            code="SITE",
            label="Requested site",
            passed=(
                requested_site is not None
                and requested_site.is_active
                and visit_site is not None
                and visit_site.id == requested_site_id
            ),
            reason_code="SITE_MISMATCH",
            detail=(
                "The token is valid for the requested active site."
                if (
                    requested_site is not None
                    and requested_site.is_active
                    and visit_site is not None
                    and visit_site.id == requested_site_id
                )
                else "The token is not valid for the requested site."
            ),
            corrective_action="Direct the person to the site named on their access token.",
        ),
    ]

    if visit is None or person is None:
        checks.append(
            _check(
                code="VISIT",
                label="Visit association",
                passed=False,
                reason_code="VISIT_UNAVAILABLE",
                detail="The access token is not associated with an available visit.",
                corrective_action="Contact the site manager to review the token record.",
            )
        )
        identity: dict[str, Any] | None = None
    else:
        invitation_ready = (
            invitation is not None
            and invitation.person_id == person.id
            and invitation.site_id == visit.site_id
            and invitation.response_status == "accepted"
        )
        checks.append(
            _check(
                code="INVITATION",
                label="Accepted invitation and registration",
                passed=invitation_ready,
                reason_code="INVITATION_NOT_ACCEPTED",
                detail=(
                    "The accepted invitation is linked to this person and visit."
                    if invitation_ready
                    else "No accepted invitation is linked to this person and visit."
                ),
                corrective_action="Ask the recipient to accept and complete their invitation.",
            )
        )
        checks.extend(
            [
                _check(
                    code="VISIT_WINDOW",
                    label="Visit time window",
                    passed=visit.starts_at <= evaluated_at <= visit.ends_at,
                    reason_code="VISIT_OUTSIDE_WINDOW",
                    detail=(
                        "The visit is within its permitted time window."
                        if visit.starts_at <= evaluated_at <= visit.ends_at
                        else "The visit is outside its permitted time window."
                    ),
                    corrective_action="Ask the site manager to reschedule or extend the visit.",
                ),
                _check(
                    code="VISIT_STATUS",
                    label="Visit status",
                    # Registration creates a planned visit. A planned visit
                    # remains eligible for evaluation until its first entry;
                    # all other gate checks still determine the final decision.
                    passed=visit.status in (VisitStatus.PLANNED, VisitStatus.ACTIVE),
                    reason_code="VISIT_NOT_ACTIVE",
                    detail=(
                        "The visit is planned or active."
                        if visit.status in (VisitStatus.PLANNED, VisitStatus.ACTIVE)
                        else "The visit is not active."
                    ),
                    corrective_action="Contact the site manager to review the visit status.",
                ),
                _check(
                    code="PERSON_STANDING",
                    label="Person standing",
                    passed=person.standing is PersonStanding.ACTIVE,
                    reason_code="PERSON_NOT_ACTIVE",
                    detail=(
                        "The person's standing is active."
                        if person.standing is PersonStanding.ACTIVE
                        else "The person's standing does not permit access."
                    ),
                    corrective_action="Contact the site manager to review the person record.",
                ),
            ]
        )
        blacklisted = _is_blacklisted(
            database,
            person=person,
            evaluated_at=evaluated_at,
        )
        checks.append(
            _check(
                code="BLACKLIST",
                label="Person and company blacklist",
                passed=not blacklisted,
                reason_code="PERSON_BLACKLISTED",
                detail=(
                    "No active person or company blacklist entry applies."
                    if not blacklisted
                    else "An active person or company blacklist entry blocks access."
                ),
                corrective_action=(
                    "Open the person record or contact the site manager; do not override "
                    "the backend decision."
                ),
            )
        )

        for requirement in _requirement_checks(
            database,
            visit=visit,
            person=person,
            evaluated_at=evaluated_at,
        ):
            passed = not bool(requirement["blocking"])
            reason_code, action = _requirement_reason(requirement)
            checks.append(
                _check(
                    code=str(requirement["code"]),
                    label=str(requirement["label"]),
                    passed=passed,
                    reason_code=reason_code,
                    detail=str(requirement["detail"]),
                    corrective_action=action,
                )
            )

        # Site configuration must not accidentally omit the verified identity
        # evidence required by the invitation-to-gate workflow.
        if not any(
            check["code"] in {"ID_CARD", "DRIVING_LICENCE"} for check in checks
        ):
            requirement = _identity_check(
                database, person=person, evaluated_at=evaluated_at
            )
            reason_code, action = _requirement_reason(requirement)
            checks.append(
                _check(
                    code=str(requirement["code"]),
                    label=str(requirement["label"]),
                    passed=not bool(requirement["blocking"]),
                    reason_code=reason_code,
                    detail=str(requirement["detail"]),
                    corrective_action=action,
                )
            )

        approved = _active_approval(database, visit.id) is not None
        checks.append(
            _check(
                code="APPROVAL",
                label="Current visit approval",
                passed=approved,
                reason_code="APPROVAL_MISSING",
                detail=(
                    "A current approved eligibility decision exists."
                    if approved
                    else "No current approved eligibility decision exists."
                ),
                corrective_action="Request compliance or site-manager approval.",
            )
        )
        identity = _identity_snapshot(
            person=person,
            presentation_reference=presentation_reference,
        )
        identity_available = identity["provider_reference"] != "identity-provider-unavailable"
        checks.append(
            _check(
                code="IDENTITY",
                label="Deterministic identity verification",
                passed=bool(identity["match"]) and identity_available,
                reason_code=(
                    "IDENTITY_MISMATCH"
                    if identity_available
                    else "IDENTITY_PROVIDER_UNAVAILABLE"
                ),
                detail=(
                    "The synthetic identity presentation matches the registered person."
                    if bool(identity["match"]) and identity_available
                    else (
                        "The identity provider is currently unavailable."
                        if not identity_available
                        else "The synthetic identity presentation does not match the "
                        "registered person."
                    )
                ),
                corrective_action=(
                    "Retry the deterministic identity check or select a demo scenario."
                    if not identity_available
                    else "Offer manual review without creating presence."
                ),
            )
        )

    checks.append(
        _check(
            code="PHYSICAL_DOCUMENT_COMPARISON",
            label="Operator physical document comparison",
            passed=comparison_confirmed,
            reason_code="PHYSICAL_COMPARISON_REQUIRED",
            detail=(
                "The operator confirmed comparison of invitation uploads with presented documents."
                if comparison_confirmed else
                "The operator has not confirmed comparing the invitation uploads with physical documents."
            ),
            corrective_action="Compare the displayed invitation uploads with the physical documents and confirm the comparison.",
        )
    )
    checks = _ordered_checks(checks)
    decision, reason_codes, reasons, actions = _decision_outcome(checks)

    event = GateEvent(
        id=uuid.uuid4(),
        token_id=token.id,
        requested_site_id=requested_site_id,
        visit_id=visit.id if visit else None,
        person_id=person.id if person else None,
        operator_id=actor.id,
        scanned_reference_hash=reference_hash,
        decision=decision,
        reason_codes=reason_codes,
        reasons=reasons,
        corrective_actions=actions,
        checks=checks,
        identity_snapshot=(
            {
                **identity,
                "evaluated_at": identity["evaluated_at"].isoformat(),
            }
            if identity is not None
            else {}
        ),
        occurred_at=occurred_at,
    )
    database.add(event)
    database.flush()

    if identity is not None and person is not None:
        database.add(
            IdentityVerification(
                id=uuid.uuid4(),
                gate_event_id=event.id,
                person_id=person.id,
                presentation_reference=presentation_reference,
                is_match=bool(identity["match"]),
                confidence=float(identity["confidence"]),
                provider_mode=str(identity["mode"]),
                provider_reference=str(identity["provider_reference"]),
                evaluated_at=identity["evaluated_at"],
            )
        )
    if decision is GateDecision.GRANT and visit is not None and person is not None:
        record_gate_entry(
            database,
            actor=actor,
            gate_event=event,
        )
    append_audit_event(
        database,
        actor=actor,
        action="gate.granted" if decision is GateDecision.GRANT else "gate.denied",
        entity_type="gate_event",
        entity_id=str(event.id),
        reason=reasons[0],
        details={
            "decision": decision.value,
            "reason_codes": reason_codes,
            "visit_id": str(event.visit_id) if event.visit_id else None,
            "person_id": str(event.person_id) if event.person_id else None,
            "identity_mode": identity["mode"] if identity else None,
            "comparison_confirmed": comparison_confirmed,
            "synthetic": True,
        },
    )
    return _response(event=event, identity=identity)
