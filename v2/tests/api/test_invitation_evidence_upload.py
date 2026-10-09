"""Regression coverage for invitation identity-evidence upload validation."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models import EvidenceType, Population
from app.services import workflows


def test_identity_upload_checks_invitation_population_before_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the wrong identity type without storing any private bytes."""

    invitation = SimpleNamespace(
        id=uuid.uuid4(),
        population=Population.PERMANENT_CONTRACTOR,
        person_id=uuid.uuid4(),
        response_status="accepted",
        registration_completed_at=object(),
    )
    actor = SimpleNamespace(id=uuid.uuid4())
    checked: list[bool] = []

    def require_access(database: object, account: object, record: object) -> None:
        """Record that object authorization precedes identity validation."""
        checked.append(account is actor and record is invitation)

    class Storage:
        """Fail if a rejected upload attempts to persist private content."""

        def put(self, content: bytes) -> None:
            """Reject unexpected storage for an invalid evidence type."""
            raise AssertionError("Rejected upload must not reach private storage.")

    monkeypatch.setattr(workflows, "_get_invitation", lambda *_args: invitation)
    monkeypatch.setattr(workflows, "_require_registration_access", require_access)

    with pytest.raises(workflows.WorkflowError, match="Drivers must upload"):
        workflows.upload_evidence(
            object(),
            actor=actor,
            invitation_id=invitation.id,
            evidence_type=EvidenceType.DRIVING_LICENCE,
            filename="demo-licence.txt",
            media_type="text/plain",
            content=b"DEMO licence",
            storage=Storage(),
            allow_real_identity_document=False,
        )

    assert checked == [True]
