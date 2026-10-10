"""Private evidence-storage provider boundary."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from botocore.exceptions import ClientError

from sqlalchemy import text
from sqlalchemy.orm import Session

_STORAGE_REFERENCE = re.compile(r"^objects/[0-9a-f]{2}/[0-9a-f]{64}$")


def _content_reference(content: bytes) -> str:
    """Return the deterministic private reference for the supplied bytes."""

    digest = hashlib.sha256(content).hexdigest()
    return f"objects/{digest[:2]}/{digest}"


def lock_private_reference(database: Session, reference: str) -> None:
    """Serialize reference creation and erasure until this transaction ends.

    PostgreSQL advisory locks also cover references with no queue row yet.
    SQLite has no equivalent; isolated SQLite tests exercise the call ordering.
    """

    if not _STORAGE_REFERENCE.fullmatch(reference):
        return  # Seeded demo references are not content-addressed files.
    if database.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(
            hashlib.sha256(reference.encode("ascii")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        database.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
        )


def put_private_reference(
    database: Session, storage: StorageProvider, content: bytes
) -> StoredObject:
    """Lock a content-addressed reference before writing its private bytes.

    Even if a prior erasure just finished, put restores the bytes before the
    caller may commit a new reference. The caller must commit or roll back.
    """

    lock_private_reference(database, _content_reference(content))
    return storage.put(content)


# PUBLIC_INTERFACE
@dataclass(frozen=True)
class StoredObject:
    """Metadata returned after private object persistence."""

    reference: str
    sha256: str
    size_bytes: int
    mode: str


# PUBLIC_INTERFACE
class StorageProvider(Protocol):
    """Provider contract for private object creation, retrieval, and deletion."""

    # PUBLIC_INTERFACE
    def put(self, content: bytes) -> StoredObject:
        """Store validated bytes and return an opaque reference."""

    # PUBLIC_INTERFACE
    def get(self, reference: str) -> bytes:
        """Retrieve bytes for a previously authorized opaque reference."""

    # PUBLIC_INTERFACE
    def delete(self, reference: str) -> None:
        """Remove one validated private object; an absent object is already erased."""


# PUBLIC_INTERFACE
class LocalStorage:
    """Private filesystem storage rooted outside the public web application."""

    # PUBLIC_INTERFACE
    def __init__(self, root: str) -> None:
        """Initialize local storage at the configured private root."""

        self._root = Path(root)

    # PUBLIC_INTERFACE
    def put(self, content: bytes) -> StoredObject:
        """Persist bytes at a deterministic content-addressed private path."""

        digest = hashlib.sha256(content).hexdigest()
        reference = f"objects/{digest[:2]}/{digest}"
        target = self._resolve(reference)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(content)
        return StoredObject(
            reference=reference,
            sha256=digest,
            size_bytes=len(content),
            mode="LOCAL",
        )

    # PUBLIC_INTERFACE
    def get(self, reference: str) -> bytes:
        """Read an object after validating its opaque reference."""

        target = self._resolve(reference)
        if not target.is_file():
            raise FileNotFoundError("Private evidence content is unavailable.")
        return target.read_bytes()

    # PUBLIC_INTERFACE
    def delete(self, reference: str) -> None:
        """Remove only an existing regular file within the private storage root."""

        target = self._resolve(reference)
        if target.is_symlink():
            raise ValueError("Private storage object is a symbolic link.")
        if target.exists():
            if not target.is_file():
                raise ValueError("Private storage object is not a regular file.")
            target.unlink()

    def _resolve(self, reference: str) -> Path:
        if not _STORAGE_REFERENCE.fullmatch(reference):
            raise ValueError("Invalid private storage reference.")
        target = (self._root / reference).resolve()
        root = self._root.resolve()
        if root not in target.parents:
            raise ValueError("Storage reference escapes the private root.")
        return target


# PUBLIC_INTERFACE
class S3Storage:
    """Private S3-compatible object storage with server-side encryption.

    Objects use the same content-addressed references as local storage, so the
    database never needs to know which provider holds the bytes. The bucket must
    be private; this class never creates public URLs or presigned links.
    """

    # PUBLIC_INTERFACE
    def __init__(self, client: Any, bucket: str) -> None:
        """Wrap a boto3 S3 client and the private bucket it writes to."""

        self._client = client
        self._bucket = bucket

    # PUBLIC_INTERFACE
    def put(self, content: bytes) -> StoredObject:
        """Persist bytes under a deterministic content-addressed key."""

        digest = hashlib.sha256(content).hexdigest()
        reference = f"objects/{digest[:2]}/{digest}"
        if not self._exists(reference):
            self._client.put_object(
                Bucket=self._bucket,
                Key=reference,
                Body=content,
                ServerSideEncryption="AES256",
            )
        return StoredObject(
            reference=reference,
            sha256=digest,
            size_bytes=len(content),
            mode="EXTERNAL",
        )

    # PUBLIC_INTERFACE
    def get(self, reference: str) -> bytes:
        """Read an object after validating its opaque reference."""

        self._check(reference)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=reference)
        except self._client.exceptions.NoSuchKey as error:
            raise FileNotFoundError("Private evidence content is unavailable.") from error
        return response["Body"].read()

    # PUBLIC_INTERFACE
    def delete(self, reference: str) -> None:
        """Remove one object; S3 treats an absent key as already erased."""

        self._check(reference)
        self._client.delete_object(Bucket=self._bucket, Key=reference)

    def _exists(self, reference: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=reference)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    @staticmethod
    def _check(reference: str) -> None:
        if not _STORAGE_REFERENCE.fullmatch(reference):
            raise ValueError("Invalid private storage reference.")
