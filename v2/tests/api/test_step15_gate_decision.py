"""Focused VAL-06 contract tests for authoritative gate decisions.

The tests isolate the existing service orchestration from PostgreSQL while
retaining its actual persistence objects and audit calls. This makes the fixed
server-side precedence, persisted snapshots, and API response contract
deterministic without changing any established workflow behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import (
    AccessTokenStatus,
    GateDecision,
    GateEvent,
    IdentityVerification,
    Invitation,
    PersonStanding,
    VisitStatus,
)
from app.providers.identity import IdentityVerificationResult
from app.routes import batch4 as batch4_routes
from app.services import batch4


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
TOKEN_REFERENCE = "opaque-token-reference-for-step15"


class RecordingDatabase:
    """Small unit-of-work double retaining exactly what the service persists."""

    def __init__(self, token: SimpleNamespace, records: dict[uuid.UUID, Any]) -> None:
        self.token = token
        self.records = records
        self.added: list[Any] = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def scalar(self, statement: Any) -> Any:
        """Resolve token and invitation independently."""

        entity = statement.column_descriptions[0]["entity"]
        if entity.__name__ == "AccessToken":
            return self.token
        if entity is Invitation:
            return self.invitation
        raise AssertionError(f"Unexpected scalar query for {entity!r}.")

    def get(self, _: Any, record_id: uuid.UUID) -> Any:
        """Return a preconfigured domain record by identifier."""

        return self.records.get(record_id)

    def add(self, record: Any) -> None:
        """Retain persisted records for test assertions."""

        self.added.append(record)

    def flush(self) -> None:
        """Record that the service flushes its immutable event snapshot."""

        self.flush_count += 1

    def commit(self) -> None:
        """Record a successful route-level unit-of-work commit."""

        self.commit_count += 1

    def rollback(self) -> None:
        """Record a route-level transaction rollback."""

        self.rollback_count += 1


@dataclass
class GateHarness:
    """Mutable state and deterministic collaborators for one gate evaluation."""

    actor: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(id=uuid.uuid4())
    )
    requested_site: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(id=uuid.uuid4(), is_active=True)
    )
    visit_site: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(id=uuid.uuid4(), is_active=True)
    )
    person: SimpleNamespace = field(
        default_factory=lambda: SimpleNamespace(
            id=uuid.uuid4(),
            standing=PersonStanding.ACTIVE,
            source_metadata={"scenario": "valid"},
            seed_key="step15-person",
        )
    )
    visit: SimpleNamespace | None = None
    token: SimpleNamespace | None = None
    invitation: SimpleNamespace | None = None
    approved: bool = True
    blacklisted: bool = False
    requirements: list[dict[str, Any]] = field(default_factory=list)
    identity_matches: bool = True
    provider_unavailable: bool = False
    comparison_confirmed: bool = True
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    database: RecordingDatabase | None = None

    def __post_init__(self) -> None:
        """Build an otherwise-valid token, visit, and in-memory record map."""

        self.visit_site = self.requested_site
        self.visit = SimpleNamespace(
            id=uuid.uuid4(),
            person_id=self.person.id,
            site_id=self.visit_site.id,
            starts_at=NOW - timedelta(hours=1),
            ends_at=NOW + timedelta(hours=1),
            status=VisitStatus.ACTIVE,
        )
        self.token = SimpleNamespace(
            id=uuid.uuid4(),
            visit_id=self.visit.id,
            status=AccessTokenStatus.ACTIVE,
            expires_at=NOW + timedelta(hours=1),
            valid_from=None,
        )
        self.invitation = SimpleNamespace(
            id=uuid.uuid4(),
            visit_id=self.visit.id,
            person_id=self.person.id,
            site_id=self.visit_site.id,
            response_status="accepted",
            identity_document_sha256="a" * 64,
        )
        self.database = RecordingDatabase(
            self.token,
            {
                self.requested_site.id: self.requested_site,
                self.visit_site.id: self.visit_site,
                self.visit.id: self.visit,
                self.person.id: self.person,
            },
        )
        self.database.invitation = self.invitation

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Replace external collaborators while preserving evaluator behavior."""

        assert self.database is not None

        monkeypatch.setattr(batch4, "_now", lambda: NOW)
        monkeypatch.setattr(batch4, "_is_blacklisted", lambda *_args, **_kwargs: self.blacklisted)
        monkeypatch.setattr(
            batch4,
            "_active_approval",
            lambda *_args, **_kwargs: object() if self.approved else None,
        )
        monkeypatch.setattr(
            batch4,
            "_requirement_checks",
            lambda *_args, **_kwargs: self.requirements,
        )
        monkeypatch.setattr(
            batch4,
            "_identity_check",
            lambda *_args, **_kwargs: {
                "code": "ID_CARD",
                "label": "Verified ID card",
                "status": "passed",
                "blocking": False,
                "detail": "Verified ID card is current.",
            },
        )
        monkeypatch.setattr(batch4, "current_demo_time", lambda _db: NOW)
        monkeypatch.setattr(batch4, "record_gate_entry", lambda *_args, **_kwargs: None)

        harness = self

        class IdentityProvider:
            """Deterministic test provider covering match and outage behavior."""

            def verify(
                self,
                *,
                person: Any,
                presentation_reference: str,
            ) -> IdentityVerificationResult:
                """Return the configured provider result for the current harness."""

                del person, presentation_reference
                if harness.provider_unavailable:
                    raise RuntimeError("Identity provider unavailable")
                return IdentityVerificationResult(
                    is_match=harness.identity_matches,
                    confidence=0.96 if harness.identity_matches else 0.18,
                    mode="DEMO",
                    provider_reference=(
                        "step15-identity-match"
                        if harness.identity_matches
                        else "step15-identity-mismatch"
                    ),
                    evaluated_at=NOW,
                )

        monkeypatch.setattr(
            batch4,
            "get_identity_verification_provider",
            lambda: IdentityProvider(),
        )

        def record_audit(_: Any, **kwargs: Any) -> SimpleNamespace:
            harness.audit_events.append(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(batch4, "append_audit_event", record_audit)

    def evaluate(self) -> dict[str, Any]:
        """Evaluate the configured gate state through the real service."""

        assert self.database is not None
        return batch4.evaluate_gate_access(
            self.database,
            actor=self.actor,
            token_reference=TOKEN_REFERENCE,
            requested_site_id=self.requested_site.id,
            presentation_reference="step15-presentation",
            comparison_confirmed=self.comparison_confirmed,
        )

    @property
    def event(self) -> GateEvent:
        """Return the single persisted immutable gate event."""

        assert self.database is not None
        events = [record for record in self.database.added if isinstance(record, GateEvent)]
        assert len(events) == 1
        return events[0]

    @property
    def identity_verification(self) -> IdentityVerification:
        """Return the single identity-verification record persisted for a visit."""

        assert self.database is not None
        records = [
            record
            for record in self.database.added
            if isinstance(record, IdentityVerification)
        ]
        assert len(records) == 1
        return records[0]


@pytest.fixture
def gate_harness(monkeypatch: pytest.MonkeyPatch) -> GateHarness:
    """Provide an otherwise-valid gate state wired to deterministic collaborators."""

    harness = GateHarness()
    harness.install(monkeypatch)
    return harness


def _failed_requirement(
    code: str,
    *,
    status: str,
    detail: str,
) -> dict[str, Any]:
    """Build the service-level compliance input shape for one blocking failure."""

    return {
        "code": code,
        "label": code.replace("_", " ").title(),
        "status": status,
        "blocking": True,
        "detail": detail,
    }


def _assert_persistence(
    harness: GateHarness,
    response: dict[str, Any],
    *,
    decision: GateDecision,
    audit_action: str,
    identity_expected: bool = True,
) -> None:
    """Assert the immutable event, optional identity result, and audit snapshot."""

    event = harness.event
    assert harness.database is not None
    assert harness.database.flush_count >= 1
    assert event.id == response["gate_event_id"]
    assert event.decision is decision
    assert event.checks == response["checks"]
    assert event.reason_codes == response["reason_codes"]
    assert event.reasons == response["reasons"]
    assert event.corrective_actions == response["corrective_actions"]
    assert len(harness.audit_events) == 1
    assert harness.audit_events[0]["action"] == audit_action
    assert harness.audit_events[0]["entity_id"] == str(event.id)

    if identity_expected:
        identity = harness.identity_verification
        assert identity.gate_event_id == event.id
        assert identity.person_id == harness.person.id
        assert identity.presentation_reference == "step15-presentation"
    else:
        assert not any(
            isinstance(record, IdentityVerification)
            for record in harness.database.added
        )


def _assert_single_primary_denial(
    response: dict[str, Any],
    *,
    reason_code: str,
) -> None:
    """Assert the response exposes exactly one backend-authoritative denial."""

    assert response["decision"] is GateDecision.DENY
    assert response["reason_codes"] == [reason_code]
    assert len(response["reasons"]) == 1
    assert len(response["corrective_actions"]) == 1
    assert response["primary_reason_code"] == reason_code
    assert response["primary_reason"] == response["reasons"][0]
    assert response["next_action"] == response["corrective_actions"][0]


def test_valid_gate_grant_persists_identity_event_and_grant_audit(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 A: a fully eligible current visit receives one authoritative grant."""

    response = gate_harness.evaluate()

    assert response["decision"] is GateDecision.GRANT
    assert response["primary_reason_code"] == "ACCESS_GRANTED"
    assert response["primary_reason"] == "All mandatory server-side gate checks passed."
    assert response["next_action"] == "Record entry when the person passes the physical gate."
    assert response["reason_codes"] == []
    assert all(check["status"] == "passed" for check in response["checks"])
    assert response["identity"]["match"] is True
    assert gate_harness.audit_events[0]["details"]["comparison_confirmed"] is True
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.GRANT,
        audit_action="gate.granted",
    )


def test_gate_event_uses_live_time_while_eligibility_uses_demo_time(
    gate_harness: GateHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grant's persisted and returned time is not the saved eligibility clock."""

    live_at = NOW - timedelta(days=3)
    evaluated_times: list[datetime] = []
    monkeypatch.setattr(batch4, "_now", lambda: live_at)
    monkeypatch.setattr(batch4, "current_demo_time", lambda _db: NOW)
    monkeypatch.setattr(
        batch4,
        "_is_blacklisted",
        lambda _db, *, person, evaluated_at: evaluated_times.append(evaluated_at) or False,
    )

    response = gate_harness.evaluate()

    assert response["decision"] is GateDecision.GRANT
    assert evaluated_times == [NOW]
    assert gate_harness.event.occurred_at == live_at
    assert response["occurred_at"] == live_at


def test_invalid_token_denial_uses_live_event_time(
    gate_harness: GateHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even an unresolved presentation records its actual server event time."""

    live_at = NOW - timedelta(days=3)
    monkeypatch.setattr(batch4, "_now", lambda: live_at)
    assert gate_harness.database is not None
    gate_harness.database.token = None

    response = gate_harness.evaluate()

    assert response["decision"] is GateDecision.DENY
    assert gate_harness.event.occurred_at == live_at
    assert response["occurred_at"] == live_at


def test_planned_registered_visit_can_pass_gate_without_changing_status(
    gate_harness: GateHarness,
) -> None:
    """An approved, otherwise-eligible registered visit may arrive still planned."""

    assert gate_harness.visit is not None
    gate_harness.visit.status = VisitStatus.PLANNED

    response = gate_harness.evaluate()

    assert response["decision"] is GateDecision.GRANT
    assert response["primary_reason_code"] == "ACCESS_GRANTED"
    assert next(
        check for check in response["checks"] if check["code"] == "VISIT_STATUS"
    )["status"] == "passed"
    assert gate_harness.visit.status is VisitStatus.PLANNED
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.GRANT,
        audit_action="gate.granted",
    )


@pytest.mark.parametrize(
    "visit_status",
    [VisitStatus.BLOCKED, VisitStatus.CANCELLED, VisitStatus.COMPLETED],
)
def test_ineligible_visit_status_still_denies_gate_entry(
    gate_harness: GateHarness,
    visit_status: VisitStatus,
) -> None:
    """A valid token and approval do not override a blocked or closed visit."""

    assert gate_harness.visit is not None
    gate_harness.visit.status = visit_status

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="VISIT_NOT_ACTIVE")
    status_check = next(
        check for check in response["checks"] if check["code"] == "VISIT_STATUS"
    )
    assert status_check["status"] == "failed"
    assert status_check["blocking"] is True
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_planned_visit_without_approval_remains_denied(
    gate_harness: GateHarness,
) -> None:
    """Allowing planned visits does not bypass the current approval check."""

    assert gate_harness.visit is not None
    gate_harness.visit.status = VisitStatus.PLANNED
    gate_harness.approved = False

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="APPROVAL_MISSING")
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_missing_physical_document_comparison_denies_access(
    gate_harness: GateHarness,
) -> None:
    """An otherwise eligible visit cannot grant entry without operator confirmation."""

    gate_harness.comparison_confirmed = False

    response = gate_harness.evaluate()

    _assert_single_primary_denial(
        response, reason_code="PHYSICAL_COMPARISON_REQUIRED"
    )
    comparison_check = next(
        check
        for check in response["checks"]
        if check["code"] == "PHYSICAL_DOCUMENT_COMPARISON"
    )
    assert comparison_check["status"] == "failed"
    assert comparison_check["blocking"] is True
    assert gate_harness.audit_events[0]["details"]["comparison_confirmed"] is False
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_missing_accepted_invitation_denies_access(gate_harness: GateHarness) -> None:
    """An issued token cannot bypass an unaccepted invitation."""

    assert gate_harness.invitation is not None
    gate_harness.invitation.response_status = "pending"

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="INVITATION_NOT_ACCEPTED")
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_confirmed_comparison_grants_without_a_presented_id_scan(
    gate_harness: GateHarness,
) -> None:
    """A physical-document comparison needs no separate presented-ID scan."""

    response = gate_harness.evaluate()

    assert response["decision"] is GateDecision.GRANT
    assert response["primary_reason_code"] == "ACCESS_GRANTED"
    assert not any(
        check["code"] == "IDENTITY_DOCUMENT_MATCH" for check in response["checks"]
    )
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.GRANT,
        audit_action="gate.granted",
    )


def test_repeated_evaluations_do_not_require_a_new_presented_id_scan(
    gate_harness: GateHarness,
) -> None:
    """Independent requests reevaluate live eligibility without scan state."""

    first = gate_harness.evaluate()
    second = gate_harness.evaluate()

    assert first["decision"] is GateDecision.GRANT
    assert second["decision"] is GateDecision.GRANT
    assert first["gate_event_id"] != second["gate_event_id"]
    assert len(gate_harness.audit_events) == 2
    assert all(event["action"] == "gate.granted" for event in gate_harness.audit_events)


def test_a_token_is_refused_before_its_entry_time_and_accepted_after_it(
    gate_harness: GateHarness,
) -> None:
    """The entry time staff set on the QR is enforced at the gate."""

    assert gate_harness.token is not None
    gate_harness.token.valid_from = NOW + timedelta(hours=1)
    early = gate_harness.evaluate()
    _assert_single_primary_denial(early, reason_code="TOKEN_NOT_YET_VALID")

    gate_harness.token.valid_from = NOW - timedelta(minutes=1)
    assert gate_harness.evaluate()["decision"] is GateDecision.GRANT


def test_expired_token_is_the_primary_denial(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 B: expired/inactive token failures take precedence over later checks."""

    assert gate_harness.token is not None
    gate_harness.token.expires_at = NOW - timedelta(seconds=1)

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="TOKEN_EXPIRED")
    assert next(check for check in response["checks"] if check["code"] == "TOKEN")[
        "status"
    ] == "failed"
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_wrong_site_is_the_primary_denial(gate_harness: GateHarness) -> None:
    """VAL-06 C: a valid token cannot grant access at a different active site."""

    gate_harness.requested_site = SimpleNamespace(id=uuid.uuid4(), is_active=True)
    assert gate_harness.database is not None
    gate_harness.database.records[gate_harness.requested_site.id] = gate_harness.requested_site

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="SITE_MISMATCH")
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_missing_approval_is_actionable_when_prior_checks_pass(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 D: absent approval is retained as the actionable primary failure."""

    gate_harness.approved = False

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="APPROVAL_MISSING")
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_active_blacklist_precedes_compliance_approval_and_identity(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 E: an active blacklist is the authoritative denial before later checks."""

    gate_harness.blacklisted = True

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="PERSON_BLACKLISTED")
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_missing_required_evidence_is_represented_as_a_compliance_denial(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 F: required evidence failures use the configured requirement reason."""

    gate_harness.requirements = [
        _failed_requirement(
            "ID_CARD",
            status="missing",
            detail="No verified required evidence is present.",
        )
    ]

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="ID_CARD_MISSING")
    evidence_check = next(
        check for check in response["checks"] if check["code"] == "ID_CARD"
    )
    assert evidence_check["status"] == "failed"
    assert evidence_check["blocking"] is True
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_failed_required_training_is_represented_as_a_compliance_denial(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 G: failed required training maps to its existing safe action."""

    gate_harness.requirements = [
        _failed_requirement(
            "SHEQ_BASICS",
            status="failed",
            detail="The latest training result did not meet the passing score.",
        )
    ]

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="SHEQ_NOT_PASSED")
    training_check = next(
        check for check in response["checks"] if check["code"] == "SHEQ_BASICS"
    )
    assert training_check["status"] == "failed"
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_missing_required_training_denies_gate_access(
    gate_harness: GateHarness,
) -> None:
    """Missing required SHEQ training remains a blocking gate check."""

    gate_harness.requirements = [
        _failed_requirement(
            "SHEQ_BASICS",
            status="missing",
            detail="No training result is recorded.",
        )
    ]

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="SHEQ_BASICS_MISSING")
    training_check = next(
        check for check in response["checks"] if check["code"] == "SHEQ_BASICS"
    )
    assert training_check["status"] == "failed"
    assert training_check["blocking"] is True
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_identity_mismatch_is_the_primary_failure_after_prior_checks_pass(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 H: an identity mismatch denies entry and persists its result."""

    gate_harness.identity_matches = False

    response = gate_harness.evaluate()

    _assert_single_primary_denial(response, reason_code="IDENTITY_MISMATCH")
    assert response["identity"]["match"] is False
    assert gate_harness.identity_verification.is_match is False
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_identity_provider_failure_maps_to_the_documented_denial(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 I: supported provider outages become a persisted safe denial."""

    gate_harness.provider_unavailable = True

    response = gate_harness.evaluate()

    _assert_single_primary_denial(
        response,
        reason_code="IDENTITY_PROVIDER_UNAVAILABLE",
    )
    assert response["identity"]["provider_reference"] == "identity-provider-unavailable"
    assert response["identity"]["mode"] == "EXTERNAL"
    assert gate_harness.identity_verification.provider_reference == (
        "identity-provider-unavailable"
    )
    _assert_persistence(
        gate_harness,
        response,
        decision=GateDecision.DENY,
        audit_action="gate.denied",
    )


def test_multiple_failures_are_ordered_and_choose_one_repeatable_primary_result(
    gate_harness: GateHarness,
) -> None:
    """VAL-06 J: all failures remain visible while token wins stable precedence."""

    assert gate_harness.token is not None
    gate_harness.token.status = AccessTokenStatus.REVOKED
    gate_harness.blacklisted = True
    gate_harness.approved = False
    gate_harness.identity_matches = False
    gate_harness.requirements = [
        _failed_requirement(
            "ID_CARD",
            status="missing",
            detail="No verified required evidence is present.",
        ),
        _failed_requirement(
            "SHEQ_BASICS",
            status="failed",
            detail="The latest training result did not meet the passing score.",
        ),
    ]

    first_response = gate_harness.evaluate()
    second_response = gate_harness.evaluate()

    for response in (first_response, second_response):
        _assert_single_primary_denial(response, reason_code="TOKEN_INACTIVE")
        assert [check["code"] for check in response["checks"]] == [
            "TOKEN",
            "SITE",
            "INVITATION",
            "VISIT_WINDOW",
            "VISIT_STATUS",
            "PERSON_STANDING",
            "BLACKLIST",
            "ID_CARD",
            "SHEQ_BASICS",
            "APPROVAL",
            "IDENTITY",
            "PHYSICAL_DOCUMENT_COMPARISON",
        ]
        failed_codes = {
            check["code"]
            for check in response["checks"]
            if check["status"] == "failed"
        }
        assert {
            "TOKEN",
            "BLACKLIST",
            "SHEQ_BASICS",
            "ID_CARD",
            "APPROVAL",
            "IDENTITY",
        }.issubset(failed_codes)

    assert first_response["primary_reason_code"] == second_response["primary_reason_code"]
    assert first_response["primary_reason"] == second_response["primary_reason"]
    assert first_response["next_action"] == second_response["next_action"]
    assert gate_harness.database is not None
    assert len(
        [record for record in gate_harness.database.added if isinstance(record, GateEvent)]
    ) == 2
    assert len(gate_harness.audit_events) == 2
    assert all(event["action"] == "gate.denied" for event in gate_harness.audit_events)


def test_gate_evaluation_endpoint_and_openapi_expose_typed_primary_fields(
    gate_harness: GateHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VAL-06 API: the actual route serializes typed decision fields and documents them."""

    expected_response = gate_harness.evaluate()
    application = FastAPI()
    application.include_router(batch4_routes.router)

    route = next(
        route
        for route in application.routes
        if getattr(route, "path", None) == "/api/gate/evaluations"
    )
    actor_dependency = route.dependant.dependencies[0].call
    application.dependency_overrides[actor_dependency] = lambda: gate_harness.actor
    application.dependency_overrides[batch4_routes.get_db] = lambda: gate_harness.database
    monkeypatch.setattr(
        batch4_routes,
        "evaluate_gate_access",
        lambda *_args, **_kwargs: expected_response,
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/gate/evaluations",
            json={
                "token_reference": TOKEN_REFERENCE,
                "site_id": str(gate_harness.requested_site.id),
                "presentation_reference": "step15-presentation",
                "comparison_confirmed": True,
            },
        )
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 201
    assert gate_harness.database is not None
    assert gate_harness.database.commit_count == 1
    assert gate_harness.database.rollback_count == 0
    body = response.json()
    assert body["decision"] == "GRANT"
    assert body["primary_reason_code"] == "ACCESS_GRANTED"
    assert body["primary_reason"] == "All mandatory server-side gate checks passed."
    assert body["next_action"] == "Record entry when the person passes the physical gate."
    assert body["checks"][0]["code"] == "TOKEN"
    assert body["identity"]["match"] is True

    decision_schema = openapi["components"]["schemas"]["GateDecisionResponse"]
    for field_name in ("primary_reason_code", "primary_reason", "next_action"):
        assert field_name in decision_schema["properties"]
        assert field_name in decision_schema["required"]

    operation = openapi["paths"]["/api/gate/evaluations"]["post"]
    assert operation["operationId"] == "evaluate_gate_access"
    assert "fixed backend precedence" in operation["description"]
