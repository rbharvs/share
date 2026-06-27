"""Publish-vertical DI chain.

Mirrors the upload/preview verticals: the route depends on
:data:`PublishServiceDep`, never on storage/repo/invalidator directly. The
storage and repository leaf providers are reused from the upload vertical
(``get_storage``/``get_repo``) so a single config swap re-points every external
resource here too. The CDN invalidator has its own leaf provider: it returns the
real :class:`CloudFrontInvalidator` once a distribution id is configured (slice
13) and the no-op :class:`NullInvalidator` otherwise. Tests override these same
seams to back the service with moto + a recording fake.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import boto3
from fastapi import Depends

from share.config import Settings, get_settings
from share.repository import MetadataRepository
from share.storage import ObjectStorage
from share.upload import get_app_settings, get_repo, get_storage

from .invalidator import CloudFrontInvalidator, Invalidator, NullInvalidator
from .service import PublishService


@lru_cache
def _cloudfront_invalidator() -> CloudFrontInvalidator:
    """Build the real boto3 CloudFront invalidator once per warm Lambda."""

    settings = get_settings()
    return CloudFrontInvalidator(
        client=boto3.client("cloudfront", region_name=settings.region),
        distribution_id=settings.cloudfront_distribution_id,
    )


def get_invalidator() -> Invalidator:
    """The CDN invalidator.

    Returns the real :class:`CloudFrontInvalidator` when the distribution id is
    configured (post slice-13 apply), else the no-op :class:`NullInvalidator` so
    publish/unpublish stay correct before the CDN exists. Overridden in tests.
    """

    if get_settings().cloudfront_distribution_id:
        return _cloudfront_invalidator()
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
