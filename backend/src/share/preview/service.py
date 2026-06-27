"""The private-preview service — the deep module behind ``GET``/``HEAD /u/{sha}``.

It serves the authenticated private rendered artifact for a finalized content
item. Resolution always goes through the metadata lookup first (the source of
truth), so an unknown SHA fails closed as ``content_not_found`` and the artifact
key is read from the stored item rather than recomputed. A finalized item is
served regardless of publish status — the private host is authenticated, so it
exposes the owner's full library, not just the published subset.

``head_artifact`` resolves the size via an S3 ``HEAD`` so a ``HEAD /u/{sha}``
request never pulls the artifact body into memory, while ``get_artifact`` streams
the bytes. Both depend only on the :class:`ObjectStorage` and
:class:`MetadataRepository` seams — never on boto3 or FastAPI — so tests drive
them against moto-backed (or fake) instances.
"""

from __future__ import annotations

from share.errors import ContentNotFoundError
from share.repository import MetadataRepository
from share.storage import ObjectStorage


class PreviewService:
    """Reads the private rendered artifact for an authenticated content GET."""

    def __init__(
        self, *, storage: ObjectStorage, repo: MetadataRepository
    ) -> None:
        self._storage = storage
        self._repo = repo

    def _artifact_key(self, sha256: str) -> str:
        """Resolve the stored artifact key, or raise ``content_not_found``.

        The metadata item is the source of truth: a missing item means the SHA
        was never finalized, and the artifact key comes from the item rather
        than being recomputed so the two can never drift.
        """

        item = self._repo.get_content_item(sha256)
        if item is None:
            raise ContentNotFoundError()
        return item.private_artifact_key

    def get_artifact(self, sha256: str) -> bytes:
        """Return the rendered artifact bytes, or raise ``content_not_found``."""

        body = self._storage.get_object(self._artifact_key(sha256))
        if body is None:
            # Metadata exists but the artifact object is gone — fail closed.
            raise ContentNotFoundError()
        return body

    def head_artifact(self, sha256: str) -> int:
        """Return the rendered artifact size in bytes without reading the body."""

        size = self._storage.head_size(self._artifact_key(sha256))
        if size is None:
            raise ContentNotFoundError()
        return size
