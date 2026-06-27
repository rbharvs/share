"""Upload-vertical DI chain.

Mirrors the existing auth/config wiring: an env-config-derived leaf provider per
external resource (``get_storage``/``get_repo``), a service provider that
composes them, and an ``Annotated`` alias the routes depend on. Routes depend on
:data:`UploadServiceDep` — never on storage or the repository directly.

The leaf providers are ``@lru_cache``d so the real boto3 clients are built once
per warm Lambda. Tests override ``get_storage``/``get_repo`` via
``app.dependency_overrides`` (and clear afterward); the ``@lru_cache`` real
providers are overridden, not invoked, so no AWS client is constructed under
moto.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import boto3
from fastapi import Depends, Request

from share.config import Settings, get_settings
from share.repository import DynamoMetadataRepository, MetadataRepository
from share.storage import ObjectStorage, S3ObjectStorage

from .service import UploadService


@lru_cache
def get_storage() -> ObjectStorage:
    """Real private-bucket S3 storage. Overridden in tests."""

    settings = get_settings()
    return S3ObjectStorage(
        client=boto3.client("s3", region_name=settings.region),
        private_bucket=settings.private_bucket,
        public_bucket=settings.public_bucket,
    )


@lru_cache
def get_repo() -> MetadataRepository:
    """Real DynamoDB metadata repository. Overridden in tests."""

    settings = get_settings()
    return DynamoMetadataRepository(
        table_name=settings.table_name,
        resource=boto3.resource("dynamodb", region_name=settings.region),
        client=boto3.client("dynamodb", region_name=settings.region),
    )


def get_app_settings(request: Request) -> Settings:
    """The per-app :class:`Settings` (prod vs. local are swapped wholesale).

    Read off ``app.state`` — the same DI seam the verifier and CSRF guard use —
    so the content hosts in finalize URLs match the app the request hit, not the
    bare ``@lru_cache`` production default.
    """

    state = getattr(request.app, "state", None)
    settings = getattr(state, "settings", None) if state is not None else None
    return settings or get_settings()


def get_upload_service(
    storage: ObjectStorage = Depends(get_storage),
    repo: MetadataRepository = Depends(get_repo),
    settings: Settings = Depends(get_app_settings),
) -> UploadService:
    """Compose the upload service from the storage + repository seams."""

    return UploadService(
        storage=storage,
        repo=repo,
        private_host=settings.private_host,
        public_host=settings.public_host,
    )


#: Route-facing alias. Routes depend on this, never on storage/repo directly.
UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]
