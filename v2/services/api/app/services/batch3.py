"""Authoritative Batch 3 domain commands for workflow Steps 4 through 6."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AccessToken,
    AccessTokenStatus,
    Approval,
    ApprovalDecision,
    BlacklistEntry,
    ComplianceRequirement,
    ComplianceRequirementKind,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Person,
    Population,
    Role,
    TrainingModule,
    TrainingOutcome,
    TrainingResult,
    UserAccount,
    Visit,
)
from app.schemas.batch3 import BlacklistCreate, TrainingAttemptCreate, TrainingCompletionCreate
from app.services.audit import append_audit_event
from app.services.batch6 import current_demo_time
from app.services.life_saving import life_saving_check
from app.services.workflows import WorkflowError

_PRIVILEGED_ROLES = frozenset(
    {Role.SYSTEM_ADMIN, Role.COMPLIANCE, Role.SITE_MANAGER}
)
_DRIVER_POPULATIONS = frozenset(
    {Population.RENEWI_DRIVER, Population.TEMPORARY_DRIVER, Population.EXTERNAL_DRIVER}
)
_REQUIRED_TRAINING_CODES = ("sheq_basics", "vlaardingen_site_rules")


def _now() -> datetime:
    """Return the UTC current time used by Batch 3 transactional commands."""

    return datetime.now(timezone.utc)


def _get_visit(database: Session, visit_id: uuid.UUID) -> Visit:
    """Return one visit or raise the established domain not-found error."""

    visit = database.get(Visit, visit_id)
    if visit is None:
        raise WorkflowError(404, "Visit not found.")
    return visit


def _get_module(database: Session, module_id: uuid.UUID) -> TrainingModule:
    """Return one active training module or a precise workflow error."""

    module = database.get(TrainingModule, module_id)
    if module is None:
        raise WorkflowError(404, "Training module not found.")
    if not module.is_active:
        raise WorkflowError(409, "Training module is inactive.")
    return module


def _require_person_training_access(
    actor: UserAccount,
    person_id: uuid.UUID,
) -> None:
    """Allow privileged users or the matching participant to submit training."""

    if actor.role in _PRIVILEGED_ROLES:
        return
    if actor.role is Role.PARTICIPANT and actor.person_id == person_id:
        return
    raise WorkflowError(403, "You cannot complete training for this person.")


def _require_visit_token_access(actor: UserAccount, visit: Visit) -> None:
    """Allow privileged users or the matching participant to view a visit token."""

    if actor.role in _PRIVILEGED_ROLES:
        return
    if actor.role is Role.PARTICIPANT and actor.person_id == visit.person_id:
        return
    raise WorkflowError(403, "You cannot access tokens for this visit.")


def _is_blacklisted(
    database: Session,
    *,
    person: Person,
    evaluated_at: datetime,
) -> bool:
    """Return whether a currently effective person or company blacklist exists."""

    statement = select(BlacklistEntry.id).where(
        BlacklistEntry.is_active.is_(True),
        BlacklistEntry.starts_at <= evaluated_at,
        or_(
            BlacklistEntry.ends_at.is_(None),
            BlacklistEntry.ends_at > evaluated_at,
        ),
        or_(
            BlacklistEntry.person_id == person.id,
            BlacklistEntry.company_id == person.company_id,
        ),
    )
    return database.scalar(statement) is not None


def _requirement_checks(
    database: Session,
    *,
    visit: Visit,
    person: Person,
    evaluated_at: datetime,
) -> list[dict[str, Any]]:
    """Resolve configured evidence and training requirements into typed checks."""

    requirements = list(
        database.scalars(
            select(ComplianceRequirement)
            .where(
                ComplianceRequirement.site_id == visit.site_id,
                ComplianceRequirement.is_active.is_(True),
                or_(
                    ComplianceRequirement.population.is_(None),
                    ComplianceRequirement.population == person.population,
                ),
            )
            .order_by(ComplianceRequirement.code, ComplianceRequirement.id)
        ).all()
    )
    checks: list[dict[str, Any]] = []
    for requirement in requirements:
        # The person's own confirmation of the life-saving rules has no document
        # or training module behind it, so it is resolved separately.
        if requirement.requirement_kind is ComplianceRequirementKind.LIFE_SAVING_RULES:
            checks.append(
                life_saving_check(
                    database, person_id=person.id, requirement=requirement
                )
            )
            continue
        # Legacy site configurations may still contain VCA. Preserve their
        # records, but never treat a VCA certificate as an access requirement.
        if requirement.evidence_type is EvidenceType.VCA_CERTIFICATE:
            continue
        # Older configurations may contain both identity documents for a
        # driver. Ignore only the document that does not apply to this person;
        # retain the configured check and its requirement metadata otherwise.
        identity_type = (
            EvidenceType.DRIVING_LICENCE
            if person.population in _DRIVER_POPULATIONS
            else EvidenceType.ID_CARD
        )
        if (
            requirement.requirement_kind is ComplianceRequirementKind.EVIDENCE
            and requirement.evidence_type in {EvidenceType.ID_CARD, EvidenceType.DRIVING_LICENCE}
            and requirement.evidence_type is not identity_type
        ):
            continue
        if requirement.requirement_kind is ComplianceRequirementKind.EVIDENCE:
            assert requirement.evidence_type is not None
            evidence = database.scalar(
                select(Evidence)
                .where(
                    Evidence.person_id == person.id,
                    Evidence.evidence_type == requirement.evidence_type,
                    Evidence.status == EvidenceStatus.VERIFIED,
                )
                .order_by(Evidence.updated_at.desc(), Evidence.id.desc())
                .limit(1)
            )
            if evidence is None:
                status = "missing"
                detail = "No verified required evidence is present."
            elif evidence.expiry_date is not None and evidence.expiry_date < evaluated_at.date():
                status = "expired"
                detail = "The required verified evidence has expired."
            else:
                status = "passed"
                detail = "Verified required evidence is current."
        else:
            assert requirement.training_module_id is not None
            result = database.scalar(
                select(TrainingResult)
                .where(
                    TrainingResult.person_id == person.id,
                    TrainingResult.training_module_id
                    == requirement.training_module_id,
                )
                .order_by(
                    TrainingResult.completed_at.desc(),
                    TrainingResult.attempt_number.desc(),
                )
                .limit(1)
            )
            if result is None:
                status = "missing"
                detail = "No training result is recorded."
            elif result.outcome is TrainingOutcome.FAILED:
                status = "failed"
                detail = "The latest training result did not meet the passing score."
            elif result.expires_at is not None and result.expires_at <= evaluated_at:
                status = "expired"
                detail = "The latest passing training result has expired."
            else:
                status = "passed"
                detail = "The latest training result is current and passed."

        checks.append(
            {
                "code": requirement.code,
                "label": requirement.label,
                "kind": requirement.requirement_kind.value,
                "status": status,
                "blocking": requirement.is_blocking and status != "passed",
                "detail": detail,
                "requirement_id": str(requirement.id),
            }
        )
    return checks


def _identity_check(
    database: Session, *, person: Person, evaluated_at: datetime
) -> dict[str, Any]:
    """Require a reviewed identity document when no configured check covers it."""

    driver = person.population in _DRIVER_POPULATIONS
    evidence_type = EvidenceType.DRIVING_LICENCE if driver else EvidenceType.ID_CARD
    evidence = database.scalar(
        select(Evidence)
        .where(
            Evidence.person_id == person.id,
            Evidence.evidence_type == evidence_type,
            Evidence.status == EvidenceStatus.VERIFIED,
        )
        .order_by(Evidence.updated_at.desc(), Evidence.id.desc())
        .limit(1)
    )
    label = "Verified driving licence" if driver else "Verified ID card"
    if evidence is None:
        status, detail = "missing", f"No {label.lower()} is present."
    elif evidence.expiry_date is not None and evidence.expiry_date < evaluated_at.date():
        status, detail = "expired", f"The {label.lower()} has expired."
    else:
        status, detail = "passed", f"{label} is current."
    return {
        "code": "DRIVING_LICENCE" if driver else "ID_CARD",
        "label": label,
        "kind": ComplianceRequirementKind.EVIDENCE.value,
        "status": status,
        "blocking": status != "passed",
        "detail": detail,
        "requirement_id": None,
    }


# PUBLIC_INTERFACE
def list_training_modules(database: Session) -> list[TrainingModule]:
    """Return active training modules in deterministic display order."""

    statement = (
        select(TrainingModule)
        .where(TrainingModule.is_active.is_(True))
        .order_by(TrainingModule.name, TrainingModule.code)
    )
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
def list_training_results(
    database: Session,
    *,
    actor: UserAccount,
    person_id: uuid.UUID,
) -> list[TrainingResult]:
    """List scored attempts after enforcing participant ownership boundaries."""

    _require_person_training_access(actor, person_id)
    statement = (
        select(TrainingResult)
        .where(TrainingResult.person_id == person_id)
        .order_by(
            TrainingResult.completed_at.desc(),
            TrainingResult.attempt_number.desc(),
        )
    )
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
def submit_training_attempt(
    database: Session,
    *,
    actor: UserAccount,
    person_id: uuid.UUID,
    module_id: uuid.UUID,
    payload: TrainingAttemptCreate,
) -> TrainingResult:
    """Score and persist a training attempt with calculated outcome and expiry."""

    _require_person_training_access(actor, person_id)
    person = database.get(Person, person_id)
    if person is None:
        raise WorkflowError(404, "Person not found.")
    module = _get_module(database, module_id)

    answer_key = {
        str(question["id"]): int(question["correct_option"])
        for question in module.questions
    }
    if set(payload.answers) != set(answer_key):
        raise WorkflowError(
            422,
            "Answers must include exactly one selected option for every question.",
        )
    if any(
        submitted < 0
        or submitted >= len(
            next(
                question["options"]
                for question in module.questions
                if str(question["id"]) == question_id
            )
        )
        for question_id, submitted in payload.answers.items()
    ):
        raise WorkflowError(422, "One or more selected answer indexes are invalid.")

    correct_answers = sum(
        payload.answers[question_id] == correct_option
        for question_id, correct_option in answer_key.items()
    )
    score = (correct_answers * 100) // len(answer_key)
    outcome = (
        TrainingOutcome.PASSED
        if score >= module.passing_score
        else TrainingOutcome.FAILED
    )
    attempt_number = (
        database.scalar(
            select(func.coalesce(func.max(TrainingResult.attempt_number), 0)).where(
                TrainingResult.person_id == person_id,
                TrainingResult.training_module_id == module_id,
            )
        )
        or 0
    ) + 1
    completed_at = _now()
    expires_at = (
        completed_at + timedelta(days=module.validity_days)
        if outcome is TrainingOutcome.PASSED
        else None
    )

    result = TrainingResult(
        id=uuid.uuid4(),
        person_id=person_id,
        training_module_id=module_id,
        attempt_number=attempt_number,
        score=score,
        outcome=outcome,
        answers=payload.answers,
        completed_at=completed_at,
        expires_at=expires_at,
    )
    database.add(result)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action=(
            "training.completed"
            if outcome is TrainingOutcome.PASSED
            else "training.failed"
        ),
        entity_type="training_result",
        entity_id=str(result.id),
        reason=(
            f"{module.name} attempt {attempt_number} "
            f"{'passed' if outcome is TrainingOutcome.PASSED else 'failed'} "
            f"with score {score}%."
        ),
        details={
            "person_id": str(person_id),
            "module_code": module.code,
            "attempt_number": attempt_number,
            "score": score,
            "outcome": outcome.value,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "synthetic": True,
        },
    )
    return result


# PUBLIC_INTERFACE
def submit_training_completion(
    database: Session,
    *,
    actor: UserAccount,
    person_id: uuid.UUID,
    payload: TrainingCompletionCreate,
) -> list[TrainingResult]:
    """Record both admin-confirmed modules only when both are selected.

    Args:
        database: Transaction containing training modules and results.
        actor: System administrator confirming prior completion.
        person_id: Participant whose training was completed.
        payload: Both mandatory administrator confirmations.
    Returns:
        Two auditable passing results, one for each required module.
    """

    if actor.role is not Role.SYSTEM_ADMIN:
        raise WorkflowError(403, "Only an administrator can confirm training.")
    if not payload.sheq_basics or not payload.vlaardingen_site_rules:
        raise WorkflowError(422, "Confirm both required training modules before submitting.")
    if database.get(Person, person_id) is None:
        raise WorkflowError(404, "Person not found.")

    modules = list(
        database.scalars(
            select(TrainingModule).where(
                TrainingModule.code.in_(_REQUIRED_TRAINING_CODES),
                TrainingModule.is_active.is_(True),
            )
        ).all()
    )
    by_code = {module.code: module for module in modules}
    if set(by_code) != set(_REQUIRED_TRAINING_CODES):
        raise WorkflowError(409, "Both required training modules must be active.")

    completed_at = _now()
    results: list[TrainingResult] = []
    for code in _REQUIRED_TRAINING_CODES:
        module = by_code[code]
        attempt_number = (
            database.scalar(
                select(func.coalesce(func.max(TrainingResult.attempt_number), 0)).where(
                    TrainingResult.person_id == person_id,
                    TrainingResult.training_module_id == module.id,
                )
            ) or 0
        ) + 1
        result = TrainingResult(
            id=uuid.uuid4(),
            person_id=person_id,
            training_module_id=module.id,
            attempt_number=attempt_number,
            score=100,
            outcome=TrainingOutcome.PASSED,
            # Distinguish a human confirmation from answers to scored questions.
            answers={"administrator_confirmed": True},
            completed_at=completed_at,
            expires_at=completed_at + timedelta(days=module.validity_days),
        )
        database.add(result)
        database.flush()
        append_audit_event(
            database,
            actor=actor,
            action="training.completed",
            entity_type="training_result",
            entity_id=str(result.id),
            reason=f"Administrator confirmed prior completion of {module.name}.",
            details={
                "person_id": str(person_id),
                "module_code": code,
                "attempt_number": attempt_number,
                "completion_method": "administrator_confirmation",
                "expires_at": result.expires_at.isoformat(),
            },
        )
        results.append(result)
    return results


# PUBLIC_INTERFACE
def list_blacklist_entries(database: Session) -> list[BlacklistEntry]:
    """List blacklist records newest first for authorized compliance management."""

    statement = select(BlacklistEntry).order_by(
        BlacklistEntry.is_active.desc(),
        BlacklistEntry.starts_at.desc(),
        BlacklistEntry.id,
    )
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
def create_blacklist_entry(
    database: Session,
    *,
    actor: UserAccount,
    payload: BlacklistCreate,
) -> BlacklistEntry:
    """Persist an active blacklist entry and append its audit evidence."""

    if payload.person_id is not None and database.get(Person, payload.person_id) is None:
        raise WorkflowError(404, "Person not found.")
    if payload.company_id is not None:
        from app.models import Company

        if database.get(Company, payload.company_id) is None:
            raise WorkflowError(404, "Company not found.")

    now = _now()
    if payload.ends_at is not None:
        if payload.ends_at.tzinfo is None:
            raise WorkflowError(422, "Blacklist end time must include timezone information.")
        if payload.ends_at <= now:
            raise WorkflowError(422, "Blacklist end time must be in the future.")

    duplicate = database.scalar(
        select(BlacklistEntry).where(
            BlacklistEntry.is_active.is_(True),
            BlacklistEntry.person_id == payload.person_id,
            BlacklistEntry.company_id == payload.company_id,
            or_(
                BlacklistEntry.ends_at.is_(None),
                BlacklistEntry.ends_at > now,
            ),
        )
    )
    if duplicate is not None:
        raise WorkflowError(409, "An active blacklist entry already exists.")

    entry = BlacklistEntry(
        id=uuid.uuid4(),
        subject_type=payload.subject_type,
        person_id=payload.person_id,
        company_id=payload.company_id,
        reason=payload.reason,
        is_active=True,
        starts_at=now,
        ends_at=payload.ends_at,
        created_by_id=actor.id,
        revoked_by_id=None,
        revoked_at=None,
    )
    database.add(entry)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="blacklist.created",
        entity_type="blacklist_entry",
        entity_id=str(entry.id),
        reason=payload.reason,
        details={
            "subject_type": entry.subject_type.value,
            "person_id": str(entry.person_id) if entry.person_id else None,
            "company_id": str(entry.company_id) if entry.company_id else None,
            "ends_at": entry.ends_at.isoformat() if entry.ends_at else None,
            "synthetic": True,
        },
    )
    return entry


# PUBLIC_INTERFACE
def revoke_blacklist_entry(
    database: Session,
    *,
    actor: UserAccount,
    entry_id: uuid.UUID,
    reason: str,
) -> BlacklistEntry:
    """End an active blacklist entry without deleting its historical record."""

    entry = database.get(BlacklistEntry, entry_id)
    if entry is None:
        raise WorkflowError(404, "Blacklist entry not found.")
    if not entry.is_active:
        raise WorkflowError(409, "Blacklist entry is already inactive.")

    entry.is_active = False
    entry.revoked_by_id = actor.id
    entry.revoked_at = _now()
    append_audit_event(
        database,
        actor=actor,
        action="blacklist.revoked",
        entity_type="blacklist_entry",
        entity_id=str(entry.id),
        reason=reason,
        details={"synthetic": True},
    )
    return entry


# PUBLIC_INTERFACE
def evaluate_visit_compliance(
    database: Session,
    *,
    visit_id: uuid.UUID,
) -> dict[str, Any]:
    """Resolve the current authoritative compliance state for one visit."""

    visit = _get_visit(database, visit_id)
    person = database.get(Person, visit.person_id)
    if person is None:
        raise WorkflowError(409, "Visit has no valid person record.")

    evaluated_at = current_demo_time(database) or _now()
    checks: list[dict[str, Any]] = []
    if _is_blacklisted(database, person=person, evaluated_at=evaluated_at):
        checks.append(
            {
                "code": "BLACKLIST",
                "label": "Person and company blacklist",
                "kind": "blacklist",
                "status": "blocked",
                "blocking": True,
                "detail": "An active person or company blacklist entry blocks access.",
                "requirement_id": None,
            }
        )
    checks.extend(
        _requirement_checks(
            database,
            visit=visit,
            person=person,
            evaluated_at=evaluated_at,
        )
    )
    identity_code = (
        "DRIVING_LICENCE"
        if person.population in _DRIVER_POPULATIONS
        else "ID_CARD"
    )
    if not any(check["code"] == identity_code for check in checks):
        checks.append(_identity_check(database, person=person, evaluated_at=evaluated_at))
    return {
        "visit_id": visit.id,
        "person_id": person.id,
        "evaluated_at": evaluated_at,
        "eligible": not any(check["blocking"] for check in checks),
        "checks": checks,
    }


# PUBLIC_INTERFACE
def create_approval_evaluation(
    database: Session,
    *,
    actor: UserAccount,
    visit_id: uuid.UUID,
    reason: str,
) -> Approval:
    """Snapshot current compliance as a pending auditable approval evaluation."""

    evaluation = evaluate_visit_compliance(database, visit_id=visit_id)
    approval = Approval(
        id=uuid.uuid4(),
        visit_id=visit_id,
        decision=ApprovalDecision.PENDING,
        compliance_snapshot=evaluation["checks"],
        reason=reason,
        evaluated_by_id=actor.id,
        decided_by_id=None,
        # Snapshot creation is an event; the evaluated checks still use demo time.
        created_at=_now(),
        decided_at=None,
    )
    database.add(approval)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="approval.evaluated",
        entity_type="approval",
        entity_id=str(approval.id),
        reason=reason,
        details={
            "visit_id": str(visit_id),
            "eligible": evaluation["eligible"],
            "checks": evaluation["checks"],
            "synthetic": True,
        },
    )
    return approval


# PUBLIC_INTERFACE
def decide_approval(
    database: Session,
    *,
    actor: UserAccount,
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
    reason: str,
) -> Approval:
    """Record an approval decision while prohibiting approval of blocked checks."""

    approval = database.get(Approval, approval_id)
    if approval is None:
        raise WorkflowError(404, "Approval evaluation not found.")
    if approval.decision is not ApprovalDecision.PENDING:
        raise WorkflowError(409, "Only a pending approval can be decided.")

    # Re-evaluate instead of trusting a stale snapshot: an earlier VCA check
    # must not block approval, and newly failing non-VCA checks must still block.
    evaluation = evaluate_visit_compliance(database, visit_id=approval.visit_id)
    eligible = evaluation["eligible"]
    if decision is ApprovalDecision.APPROVED and not eligible:
        raise WorkflowError(
            409,
            "Approval cannot be granted while current compliance is blocked.",
        )

    approval.decision = decision
    approval.reason = reason
    approval.decided_by_id = actor.id
    approval.decided_at = _now()
    append_audit_event(
        database,
        actor=actor,
        action=f"approval.{decision.value}",
        entity_type="approval",
        entity_id=str(approval.id),
        reason=reason,
        details={
            "visit_id": str(approval.visit_id),
            "eligible_snapshot": eligible,
            "synthetic": True,
        },
    )
    return approval


def _active_approval(database: Session, visit_id: uuid.UUID) -> Approval | None:
    """Return the latest approved decision for a visit."""

    return database.scalar(
        select(Approval)
        .where(
            Approval.visit_id == visit_id,
            Approval.decision == ApprovalDecision.APPROVED,
        )
        .order_by(Approval.decided_at.desc(), Approval.id.desc())
        .limit(1)
    )


# PUBLIC_INTERFACE
def issue_access_token(
    database: Session,
    *,
    actor: UserAccount,
    visit_id: uuid.UUID,
    requested_expiry: datetime | None,
) -> tuple[AccessToken, str]:
    """Issue one opaque token only after current compliance and approval pass."""

    visit = _get_visit(database, visit_id)
    evaluation = evaluate_visit_compliance(database, visit_id=visit_id)
    if not evaluation["eligible"]:
        raise WorkflowError(
            409,
            "An access token cannot be issued while current compliance is blocked.",
        )
    if _active_approval(database, visit_id) is None:
        raise WorkflowError(
            409,
            "An access token requires a current approved eligibility decision.",
        )

    now = current_demo_time(database) or _now()
    if requested_expiry is not None:
        if requested_expiry.tzinfo is None:
            raise WorkflowError(422, "Token expiry must include timezone information.")
        expires_at = requested_expiry
    else:
        expires_at = visit.ends_at
    if expires_at <= now:
        raise WorkflowError(409, "Token expiry must be in the future.")
    if expires_at > visit.ends_at:
        raise WorkflowError(422, "Token expiry must not exceed the visit end time.")

    active_token = database.scalar(
        select(AccessToken).where(
            AccessToken.visit_id == visit_id,
            AccessToken.status == AccessTokenStatus.ACTIVE,
            AccessToken.expires_at > now,
        )
    )
    if active_token is not None:
        raise WorkflowError(409, "The visit already has an active access token.")

    reference = f"renewi-access:{secrets.token_urlsafe(32)}"
    # The demo clock controls eligibility and expiry, not when issuance occurred.
    issued_at = _now()
    token = AccessToken(
        id=uuid.uuid4(),
        visit_id=visit_id,
        reference_hash=hashlib.sha256(reference.encode("utf-8")).hexdigest(),
        status=AccessTokenStatus.ACTIVE,
        issued_by_id=actor.id,
        issued_at=issued_at,
        expires_at=expires_at,
        revoked_by_id=None,
        revoked_at=None,
        revoke_reason=None,
    )
    database.add(token)
    database.flush()
    append_audit_event(
        database,
        actor=actor,
        action="token.issued",
        entity_type="access_token",
        entity_id=str(token.id),
        reason="Issued an opaque access token for an approved eligible visit.",
        details={
            "visit_id": str(visit_id),
            "expires_at": expires_at.isoformat(),
            "reference_hash_prefix": token.reference_hash[:12],
            "synthetic": True,
        },
    )
    return token, reference


# PUBLIC_INTERFACE
def list_visit_tokens(
    database: Session,
    *,
    actor: UserAccount,
    visit_id: uuid.UUID,
) -> list[AccessToken]:
    """List safe token metadata after enforcing visit ownership boundaries."""

    visit = _get_visit(database, visit_id)
    _require_visit_token_access(actor, visit)
    statement = (
        select(AccessToken)
        .where(AccessToken.visit_id == visit_id)
        .order_by(AccessToken.issued_at.desc(), AccessToken.id.desc())
    )
    return list(database.scalars(statement).all())


# PUBLIC_INTERFACE
def revoke_access_token(
    database: Session,
    *,
    actor: UserAccount,
    token_id: uuid.UUID,
    reason: str,
) -> AccessToken:
    """Revoke an issued token without deleting token history."""

    token = database.get(AccessToken, token_id)
    if token is None:
        raise WorkflowError(404, "Access token not found.")
    if token.status is not AccessTokenStatus.ACTIVE:
        raise WorkflowError(409, "Only an active token can be revoked.")

    token.status = AccessTokenStatus.REVOKED
    token.revoked_by_id = actor.id
    token.revoked_at = _now()
    token.revoke_reason = reason
    append_audit_event(
        database,
        actor=actor,
        action="token.revoked",
        entity_type="access_token",
        entity_id=str(token.id),
        reason=reason,
        details={"visit_id": str(token.visit_id), "synthetic": True},
    )
    return token
