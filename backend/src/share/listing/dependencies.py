"""Listing-vertical DI chain.

Mirrors the upload vertical: routes depend on :data:`ContentServiceDep`, never on
the repository directly. The repository and per-app settings providers are reused
from the upload vertical (``get_repo``/``get_app_settings``) so a single config
swap re-points the content-URL hosts here too, and tests override the one
``get_repo`` seam to back the service with moto.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from share.config import Settings
from share.repository import MetadataRepository
from share.upload import get_app_settings, get_repo

from .service import ContentService


def get_content_service(
    repo: MetadataRepository = Depends(get_repo),
    settings: Settings = Depends(get_app_settings),
) -> ContentService:
    """Compose the listing service from the metadata repository seam."""

    return ContentService(
        repo=repo,
        private_host=settings.private_host,
        public_host=settings.public_host,
    )


#: Route-facing alias. Routes depend on this, never on the repository directly.
ContentServiceDep = Annotated[ContentService, Depends(get_content_service)]
