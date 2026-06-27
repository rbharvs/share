"""Private-preview DI chain.

Mirrors the upload/listing verticals: the route depends on
:data:`PreviewServiceDep`, never on storage or the repository directly. The
storage and repository leaf providers are reused from the upload vertical
(``get_storage``/``get_repo``) so a single config swap re-points every external
resource here too, and tests override those same two seams to back the service
with moto.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from share.repository import MetadataRepository
from share.storage import ObjectStorage
from share.upload import get_repo, get_storage

from .service import PreviewService


def get_preview_service(
    storage: ObjectStorage = Depends(get_storage),
    repo: MetadataRepository = Depends(get_repo),
) -> PreviewService:
    """Compose the preview service from the storage + repository seams."""

    return PreviewService(storage=storage, repo=repo)


#: Route-facing alias. The route depends on this, never on storage/repo directly.
PreviewServiceDep = Annotated[PreviewService, Depends(get_preview_service)]
