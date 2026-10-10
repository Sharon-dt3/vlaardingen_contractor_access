"""Focused Batch 8 acceptance coverage for existing public API boundaries.

The matrix supplements established lifecycle, denial, and rendered-browser
coverage. It exercises only the remaining demonstrated contracts: deterministic
credential-free providers, private evidence metadata, chronological audit reads,
and redacted dashboard output.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import providers
from app.models import EvidenceStatus, EvidenceType
from app.providers.documents import MockDocumentParser
from app.providers.identity import MockIdentityVerifier
from app.providers.notifications import InAppNotificationProvider
from app.providers.storage import LocalStorage
from app.routes import audit as audit_routes
from app.routes import batch5 as batch5_routes
from app.routes import workflows as workflow_routes


NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
PRIVATE_OUTPUT_FIELDS = {
    "presentation_reference",
    "provider_payload",
    "storage_reference",
    "token_hash",
    "token_reference",
}


class _ScalarResult:
    """Minimal SQLAlchemy scalar-result substitute for deterministic route tests."""

    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        """Return configured scalar rows in the database-provided order."""

        return self._values


class _AuditDatabase:
    """Capture the route's audit statement while returning deterministic rows."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.statement: Any | None = None

    def scalars(self, statement: Any) -> _ScalarResult:
        """Record the requested ordering statement and return configured events."""

        self.statement = statement
        return _ScalarResult(self._events)


def _evidence_record(person_id: uuid.UUID) -> SimpleNamespace:
    """Build one complete private evidence record for response-model serialization."""

    return SimpleNamespace(
        id=uuid.uuid4(),
        person_id=person_id,
        invitation_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        evidence_type=EvidenceType.VCA_CERTIFICATE,
        status=EvidenceStatus.VERIFIED,
        filename="synthetic-vca.pdf",
        media_type="application/pdf",
        size_bytes=128,
        content_sha256="a" * 64,
        storage_mode="LOCAL",
        provider_mode="DEMO",
        extracted_fields={"certificate_number": "DEMO-VCA-0001"},
        field_confidence={"certificate_number": 0.99},
        validity_assessment={},
        issue_date=date(2026, 1, 15),
        expiry_date=date(2029, 1, 15),
        review_notes="Synthetic record verified for acceptance coverage.",
        supersedes_id=None,
        uploaded_by_id=uuid.uuid4(),
        reviewed_by_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        # This internal field is intentionally present on the persistence object.
        # EvidenceResponse must never expose it through the public route.
        storage_reference="objects/aa/" + ("a" * 64),
    )


def _override_route_actor(application: FastAPI, path: str) -> None:
    """Override a route's permission dependency with a safe local test actor."""

    route = next(
        item
        for item in application.routes
        if getattr(item, "path", None) == path
    )
    actor_dependency = route.dependant.dependencies[0].call
    application.dependency_overrides[actor_dependency] = lambda: SimpleNamespace(
        id=uuid.uuid4()
    )


def test_credential_free_provider_factories_select_local_private_adapters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Default local modes select deterministic adapters and private storage."""

    settings = SimpleNamespace(
        storage_provider="local",
        storage_local_path=str(tmp_path / "private-evidence"),
        identity_verifier_provider="mock",
        ocr_provider="mock",
    )
    monkeypatch.setattr(providers, "get_settings", lambda: settings)

    document_provider = providers.get_document_extraction_provider()
    storage_provider = providers.get_storage_provider()
    identity_provider = providers.get_identity_verification_provider()
    notification_provider = providers.get_notification_provider()

    assert isinstance(document_provider, MockDocumentParser)
    assert isinstance(storage_provider, LocalStorage)
    assert isinstance(identity_provider, MockIdentityVerifier)
    assert isinstance(notification_provider, InAppNotificationProvider)

    stored = storage_provider.put(b"SYNTHETIC - NOT A REAL CREDENTIAL")
    assert stored.reference.startswith("objects/")
    assert stored.mode == "LOCAL"
    assert storage_provider.get(stored.reference) == b"SYNTHETIC - NOT A REAL CREDENTIAL"

    with pytest.raises(ValueError, match="Invalid private storage reference"):
        storage_provider.get("../outside-private-root")


def test_person_evidence_route_redacts_private_storage_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public evidence route serializes metadata without private object paths."""

    person_id = uuid.uuid4()
    record = _evidence_record(person_id)
    application = FastAPI()
    application.include_router(workflow_routes.router)
    _override_route_actor(application, "/api/people/{person_id}/evidence")
    application.dependency_overrides[workflow_routes.get_db] = lambda: object()
    monkeypatch.setattr(
        workflow_routes,
        "list_person_evidence",
        lambda *_args, **_kwargs: [record],
    )

    with TestClient(application) as client:
        response = client.get(f"/api/people/{person_id}/evidence")
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(record.id)
    assert body[0]["storage_mode"] == "LOCAL"
    assert body[0]["provider_mode"] == "DEMO"
    assert "storage_reference" not in body[0]

    evidence_schema = openapi["components"]["schemas"]["EvidenceResponse"]
    assert "storage_reference" not in evidence_schema["properties"]


def test_audit_events_route_requests_oldest_to_newest_order_and_safe_schema() -> None:
    """Audit reads request deterministic chronology and expose immutable evidence fields."""

    first = SimpleNamespace(
        id=uuid.uuid4(),
        actor_id=None,
        action="invitation.created",
        entity_type="invitation",
        entity_id="synthetic-invitation",
        reason="Synthetic invitation created.",
        details={"synthetic": True},
        occurred_at=NOW - timedelta(minutes=1),
    )
    second = SimpleNamespace(
        id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        action="evidence.verified",
        entity_type="evidence",
        entity_id="synthetic-evidence",
        reason="Synthetic evidence verified.",
        details={"synthetic": True},
        occurred_at=NOW,
    )
    database = _AuditDatabase([first, second])
    application = FastAPI()
    application.include_router(audit_routes.router)
    _override_route_actor(application, "/api/audit/events")
    application.dependency_overrides[audit_routes.get_db] = lambda: database

    with TestClient(application) as client:
        response = client.get("/api/audit/events")
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 200
    assert [event["id"] for event in response.json()] == [
        str(first.id),
        str(second.id),
    ]
    assert database.statement is not None
    rendered_statement = str(database.statement).replace("\n", " ")
    assert "ORDER BY audit_events.occurred_at, audit_events.id" in rendered_statement

    audit_schema = openapi["components"]["schemas"]["AuditEventResponse"]
    assert set(audit_schema["properties"]) == {
        "id",
        "actor_id",
        "action",
        "entity_type",
        "entity_id",
        "reason",
        "details",
        "occurred_at",
    }


def test_dashboard_route_drops_internal_token_and_provider_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dashboard serialization retains only the documented safe operational projection."""

    gate_event_id = uuid.uuid4()
    site_id = uuid.uuid4()
    visit_id = uuid.uuid4()
    person_id = uuid.uuid4()
    snapshot = {
        "as_of": NOW,
        "activity_window_started_at": NOW - timedelta(hours=24),
        "activity_hours": 24,
        "totals": {
            "site_count": 1,
            "active_visit_count": 1,
            "present_count": 1,
            "grant_count": 1,
            "denial_count": 0,
            "entry_count": 1,
            "exit_count": 0,
        },
        "sites": [
            {
                "site_id": site_id,
                "site_name": "Synthetic Site",
                "country_code": "NL",
                "active_visit_count": 1,
                "present_count": 1,
                "grant_count": 1,
                "denial_count": 0,
                "entry_count": 1,
                "exit_count": 0,
            }
        ],
        "current_presence": [
            {
                "gate_event_id": gate_event_id,
                "presence_event_id": uuid.uuid4(),
                "person_id": person_id,
                "person_name": "Synthetic Participant",
                "population": "contractor",
                "visit_id": visit_id,
                "site_id": site_id,
                "site_name": "Synthetic Site",
                "entered_at": NOW,
                "visit_ends_at": NOW + timedelta(hours=1),
                "decision": "GRANT",
            }
        ],
        "recent_decisions": [
            {
                "gate_event_id": gate_event_id,
                "occurred_at": NOW,
                "site_id": site_id,
                "site_name": "Synthetic Site",
                "visit_id": visit_id,
                "person_id": person_id,
                "person_name": "Synthetic Participant",
                "decision": "GRANT",
                "reason_codes": ["ACCESS_GRANTED"],
                # The service boundary can carry internals, but the public schema
                # must discard them before emitting the HTTP response.
                "presentation_reference": object(),
                "provider_payload": object(),
                "token_hash": object(),
                "token_reference": object(),
            }
        ],
        "presentation_reference": object(),
        "provider_payload": object(),
        "token_hash": object(),
        "token_reference": object(),
    }
    application = FastAPI()
    application.include_router(batch5_routes.router)
    _override_route_actor(application, "/api/dashboard")
    application.dependency_overrides[batch5_routes.get_db] = lambda: object()
    monkeypatch.setattr(
        batch5_routes,
        "get_dashboard_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )
    # This test checks what the route leaves out. Merging walk-up people needs a real
    # database and is covered in test_walk_up.py.
    monkeypatch.setattr(
        "app.services.walk_up.merge_walk_ups_into_dashboard",
        lambda _database, merged, **_kwargs: merged,
    )

    with TestClient(application) as client:
        response = client.get("/api/dashboard")
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["grant_count"] == 1
    assert body["recent_decisions"][0]["decision"] == "GRANT"
    assert all(field_name not in response.text for field_name in PRIVATE_OUTPUT_FIELDS)

    dashboard_schema = openapi["components"]["schemas"]["DashboardSnapshotResponse"]
    assert all(
        field_name not in dashboard_schema["properties"]
        for field_name in PRIVATE_OUTPUT_FIELDS
    )
