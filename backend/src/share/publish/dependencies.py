"""Publish-vertical DI chain.

Mirrors the upload/preview verticals: the route depends on
:data:`PublishServiceDep`, never on storage/repo/invalidator directly. The
storage and repository leaf providers are reused from the upload vertical
(``get_storage``/``get_repo``) so a single config swap re-points every external
resource here too. The CDN invalidator has its own leaf provider returning a
no-op default — the real CloudFront client is swapped in at slice 13 — and tests
override these same seams to back the service with moto + a recording fake.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from share.config import Settings
from share.repository import MetadataRepository
from share.storage import ObjectStorage
from share.upload import get_app_settings, get_repo, get_storage

from .invalidator import Invalidator, NullInvalidator
from .service import PublishService


def get_invalidator() -> Invalidator:
    """The CDN invalidator. No-op until the CloudFront client (slice 13)."""

    return NullInvalidator()


def get_publish_service(
    storage: ObjectStorage = Depends(get_storage),
    repo: MetadataRepository = Depends(get_repo),
    invalidator: Invalidator = Depends(get_invalidator),
    settings: Settings = Depends(get_app_settings),
) -> PublishService:
    """Compose the publish service from the storage + repo + invalidator seams."""

    return PublishService(
        storage=storage,
        repo=repo,
        invalidator=invalidator,
        private_host=settings.private_host,
        public_host=settings.public_host,
    )


#: Route-facing alias. Routes depend on this, never on storage/repo/invalidator.
PublishServiceDep = Annotated[PublishService, Depends(get_publish_service)]
