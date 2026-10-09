"""Configured provider composition for API domain services."""

from app.config import get_settings
from app.providers.documents import (
    AnthropicDocumentParser,
    DocumentExtractionError,
    DocumentExtractionProvider,
    ExtractionResult,
    MockDocumentParser,
)
from app.providers.identity import (
    IdentityVerificationProvider,
    IdentityVerificationResult,
    MockIdentityVerifier,
)
from app.providers.notifications import (
    InAppNotificationProvider,
    NotificationDeliveryResult,
    NotificationProvider,
)
from app.providers.storage import LocalStorage, StorageProvider, StoredObject


# PUBLIC_INTERFACE
def get_document_extraction_provider() -> DocumentExtractionProvider:
    """Return the configured server-side document extraction provider."""

    settings = get_settings()
    if settings.ocr_provider == "mock":
        return MockDocumentParser()
    if settings.ocr_provider == "anthropic" and settings.anthropic_api_key:
        api_key = settings.anthropic_api_key.get_secret_value()
        if api_key:
            return AnthropicDocumentParser(
                api_key=api_key,
                model=settings.anthropic_model,
                storage=get_storage_provider(),
            )
    raise RuntimeError("The configured document extraction adapter is unavailable.")


# PUBLIC_INTERFACE
def get_storage_provider() -> StorageProvider:
    """Return private local storage selected by validated runtime settings."""

    settings = get_settings()
    if settings.storage_provider != "local":
        raise RuntimeError(
            "The configured external storage adapter is not available in this demo."
        )
    return LocalStorage(settings.storage_local_path)


# PUBLIC_INTERFACE
def get_identity_verification_provider() -> IdentityVerificationProvider:
    """Return the deterministic identity adapter selected for the local demo."""

    settings = get_settings()
    if settings.identity_verifier_provider != "mock":
        raise RuntimeError(
            "The configured external identity adapter is not available in this demo."
        )
    return MockIdentityVerifier()


# PUBLIC_INTERFACE
def get_notification_provider() -> NotificationProvider:
    """Return the local in-app notification adapter for credential-free workflows."""

    return InAppNotificationProvider()


__all__ = [
    "DocumentExtractionProvider",
    "DocumentExtractionError",
    "ExtractionResult",
    "IdentityVerificationProvider",
    "IdentityVerificationResult",
    "InAppNotificationProvider",
    "LocalStorage",
    "AnthropicDocumentParser",
    "MockDocumentParser",
    "MockIdentityVerifier",
    "NotificationDeliveryResult",
    "NotificationProvider",
    "StorageProvider",
    "StoredObject",
    "get_document_extraction_provider",
    "get_identity_verification_provider",
    "get_notification_provider",
    "get_storage_provider",
]
