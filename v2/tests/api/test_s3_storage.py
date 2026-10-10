"""S3-compatible private storage adapter, exercised against an in-memory fake client."""

from __future__ import annotations

import hashlib
import io

import pytest
from botocore.exceptions import ClientError

from app.config import Settings
from app.providers.storage import S3Storage


class _NoSuchKey(Exception):
    pass


class _FakeS3Client:
    """Just enough of the boto3 S3 client for the adapter, with call recording."""

    class exceptions:
        NoSuchKey = _NoSuchKey

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict] = []

    def head_object(self, Bucket, Key):  # noqa: N803 - boto3 argument names
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def put_object(self, Bucket, Key, Body, ServerSideEncryption=None):  # noqa: N803
        self.put_calls.append({"Bucket": Bucket, "Key": Key, "SSE": ServerSideEncryption})
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise _NoSuchKey()
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)


@pytest.fixture()
def storage() -> tuple[S3Storage, _FakeS3Client]:
    client = _FakeS3Client()
    return S3Storage(client, "evidence"), client


def test_put_is_content_addressed_and_encrypted(storage):
    store, client = storage
    stored = store.put(b"DEMO document")
    digest = hashlib.sha256(b"DEMO document").hexdigest()
    assert stored.reference == f"objects/{digest[:2]}/{digest}"
    assert stored.sha256 == digest and stored.size_bytes == 13 and stored.mode == "EXTERNAL"
    assert client.put_calls[0]["SSE"] == "AES256"


def test_put_same_bytes_twice_writes_once(storage):
    store, client = storage
    store.put(b"same")
    store.put(b"same")
    assert len(client.put_calls) == 1


def test_get_returns_bytes_and_missing_object_is_file_not_found(storage):
    store, _ = storage
    stored = store.put(b"hello")
    assert store.get(stored.reference) == b"hello"
    store.delete(stored.reference)
    with pytest.raises(FileNotFoundError):
        store.get(stored.reference)


def test_delete_of_absent_object_is_a_no_op(storage):
    store, _ = storage
    store.delete("objects/ab/" + "a" * 64)


@pytest.mark.parametrize("reference", ["../etc/passwd", "objects/zz/abc", "", "objects/ab/" + "A" * 64])
def test_invalid_references_are_rejected(storage, reference):
    store, _ = storage
    with pytest.raises(ValueError):
        store.get(reference)
    with pytest.raises(ValueError):
        store.delete(reference)


def _settings(**overrides) -> Settings:
    values = {
        "STORAGE_PROVIDER": "s3",
        "S3_ENDPOINT_URL": "https://s3.eu-central-1.example.com",
        "S3_REGION": "eu-central-1",
        "S3_BUCKET": "evidence",
        "S3_ACCESS_KEY_ID": "key",
        "S3_SECRET_ACCESS_KEY": "secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_complete_s3_settings_select_s3():
    settings = _settings()
    settings.prepare_local_runtime()
    assert settings.storage_provider == "s3"


def test_incomplete_s3_settings_fall_back_to_local():
    settings = _settings(S3_BUCKET="")
    notices = settings.prepare_local_runtime()
    assert settings.storage_provider == "local"
    assert any("Object storage" in notice for notice in notices)
