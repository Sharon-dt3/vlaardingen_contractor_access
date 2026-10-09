"""Regression coverage for invitation evidence upload filenames and safeguards."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.models import EvidenceType, Role
from app.providers.storage import LocalStorage
from app.services import workflows
from app.services.workflows import MAX_UPLOAD_BYTES, WorkflowError, upload_evidence


class _InvitationDatabase:
    """Return a single invitation for focused upload validation tests."""

    def __init__(self, invitation: SimpleNamespace) -> None:
        self.invitation = invitation

    def get_bind(self) -> SimpleNamespace:
        """Identify this isolated stub as non-PostgreSQL for reference locking."""
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get(self, model: type[Any], identifier: uuid.UUID) -> SimpleNamespace | None:
        """Resolve only the invitation used by this test."""
        if model is workflows.Invitation and identifier == self.invitation.id:
            return self.invitation
        return None


@pytest.fixture
def upload_context(
    tmp_path: Any,
) -> tuple[_InvitationDatabase, SimpleNamespace, SimpleNamespace, LocalStorage]:
    """Provide an accepted, invitee-submitted invitation and isolated storage."""
    actor = SimpleNamespace(id=uuid.uuid4(), role=Role.SYSTEM_ADMIN, person_id=None)
    invitation = SimpleNamespace(
        id=uuid.uuid4(),
        requested_by_id=actor.id,
        response_status="accepted",
        registration_completed_at=object(),
    )
    return (
        _InvitationDatabase(invitation),
        actor,
        invitation,
        LocalStorage(str(tmp_path / "private-evidence")),
    )


def _upload(
    context: tuple[_InvitationDatabase, SimpleNamespace, SimpleNamespace, LocalStorage],
    *,
    filename: str,
    content: bytes = b"DEMO document",
    actor: SimpleNamespace | None = None,
) -> Any:
    """Exercise real invitation validation while avoiding database persistence."""
    database, authorized_actor, invitation, storage = context
    return upload_evidence(
        database,
        actor=actor or authorized_actor,
        invitation_id=invitation.id,
        evidence_type=EvidenceType.VCA_CERTIFICATE,
        filename=filename,
        media_type="application/octet-stream",
        content=content,
        storage=storage,
        allow_real_identity_document=False,
    )


@pytest.mark.parametrize(
    "filename",
    ["training record 2026.docx", "supporting-evidence", "bewijs (versie 2).zip"],
)
def test_ordinary_filenames_are_accepted_with_private_storage(
    monkeypatch: pytest.MonkeyPatch,
    upload_context: tuple[_InvitationDatabase, SimpleNamespace, SimpleNamespace, LocalStorage],
    filename: str,
) -> None:
    """Accept ordinary names without incorporating them into storage references."""
    monkeypatch.setattr(
        workflows,
        "_new_evidence",
        lambda _database, **fields: SimpleNamespace(**fields),
    )

    evidence = _upload(upload_context, filename=filename)
    storage = upload_context[3]

    assert evidence.filename == filename
    assert evidence.storage_reference.startswith("objects/")
    assert filename not in evidence.storage_reference
    assert storage.get(evidence.storage_reference) == b"DEMO document"


@pytest.mark.parametrize(
    "filename",
    ["", "../outside.txt", "folder/file.txt", "unsafe\\x00name.txt", "x" * 256],
)
def test_unsafe_filenames_are_rejected_before_storage(
    monkeypatch: pytest.MonkeyPatch,
    upload_context: tuple[_InvitationDatabase, SimpleNamespace, SimpleNamespace, LocalStorage],
    filename: str,
) -> None:
    """Reject empty, path-bearing, control-character, and oversized names."""
    storage = upload_context[3]
    monkeypatch.setattr(
        storage,
        "put",
        lambda _content: pytest.fail("Invalid filename reached private storage"),
    )

    with pytest.raises(WorkflowError, match="Upload filename is invalid") as error:
        _upload(upload_context, filename=filename)

    assert error.value.status_code == 422


def test_invitation_upload_keeps_five_mib_limit(
    monkeypatch: pytest.MonkeyPatch,
    upload_context: tuple[_InvitationDatabase, SimpleNamespace, SimpleNamespace, LocalStorage],
) -> None:
    """Reject oversized content before writing it to private storage."""
    monkeypatch.setattr(
        upload_context[3],
        "put",
        lambda _content: pytest.fail("Oversized file reached private storage"),
    )

    with pytest.raises(WorkflowError, match="between 1 byte and 5 MiB") as error:
        _upload(
            upload_context,
            filename="ordinary document.bin",
            content=b"x" * (MAX_UPLOAD_BYTES + 1),
        )

    assert error.value.status_code == 413


def test_invitation_upload_still_requires_object_access(
    monkeypatch: pytest.MonkeyPatch,
    upload_context: tuple[_InvitationDatabase, SimpleNamespace, SimpleNamespace, LocalStorage],
) -> None:
    """An unrelated account cannot write evidence for this invitation."""
    monkeypatch.setattr(
        upload_context[3],
        "put",
        lambda _content: pytest.fail("Unauthorized upload reached private storage"),
    )
    unrelated_actor = SimpleNamespace(
        id=uuid.uuid4(), role=Role.HOST, person_id=None
    )

    with pytest.raises(WorkflowError, match="You cannot access this invitation") as error:
        _upload(
            upload_context,
            filename="ordinary document.bin",
            actor=unrelated_actor,
        )

    assert error.value.status_code == 403
