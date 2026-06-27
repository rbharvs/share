"""The publish service — the deep module behind the publish/unpublish APIs.

Both operations are idempotent and self-reconciling, so a crash mid-flight (or a
metadata/object drift from any earlier partial run) converges on a re-run:

* ``publish`` regenerates the public artifact from the *canonical raw source*
  (re-rendered through the slice-03 renderer, NEVER copied from the private
  preview artifact), writes ``u/{sha}/index.html`` to the public bucket, and
  atomically updates BOTH metadata items to ``published``. Because the object is
  always (re)written it repairs a missing public object when metadata already
  says published; because the metadata is driven from the lookup item it
  reconciles metadata when the object already exists. Republish reuses the same
  SHA-addressed public URL.
* ``unpublish`` deletes the public object (idempotent if absent), computes the
  slash + no-slash CloudFront invalidation paths, and atomically marks BOTH
  metadata items ``unpublished``.

Both metadata items are written through the same single two-item transaction
finalize uses (:meth:`MetadataRepository.put_content_item`), and the list item's
sort key reuses the immutable ``created_at`` — so the lookup item and list item
can never drift. The service depends only on the :class:`ObjectStorage`,
:class:`MetadataRepository`, and :class:`Invalidator` seams (plus an injectable
clock) — never on boto3 or FastAPI.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from share.content import ContentItem, ContentItemResponse, ContentStatus
from share.errors import ContentNotFoundError, PublishFailedError
from share.renderer import render
from share.repository import MetadataRepository
from share.storage import ObjectStorage

from .invalidator import Invalidator, NullInvalidator

#: The public artifact is always a standalone HTML document.
_PUBLIC_CONTENT_TYPE = "text/html; charset=utf-8"


def _iso_ms(epoch: float) -> str:
    """Format unix-seconds as a millisecond-resolution UTC ISO-8601 timestamp."""

    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


def invalidation_paths(sha256: str) -> list[str]:
    """The slash + no-slash CloudFront paths for a published SHA.

    CloudFront treats ``/u/{sha}`` and ``/u/{sha}/`` as distinct cache keys, so
    both must be purged for the public copy to disappear from the edge.
    """

    return [f"/u/{sha256}", f"/u/{sha256}/"]


class PublishService:
    """Coordinates public-artifact regeneration, metadata, and CDN invalidation."""

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        repo: MetadataRepository,
        invalidator: Invalidator | None = None,
        private_host: str = "private.usercontent.example",
        public_host: str = "public.usercontent.example",
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._storage = storage
        self._repo = repo
        self._invalidator = invalidator or NullInvalidator()
        self._private_host = private_host
        self._public_host = public_host
        self._now = now_fn

    def _response(self, item: ContentItem) -> ContentItemResponse:
        return ContentItemResponse.from_item(
            item,
            private_host=self._private_host,
            public_host=self._public_host,
        )

    def _require_item(self, sha256: str) -> ContentItem:
        item = self._repo.get_content_item(sha256)
        if item is None:
            raise ContentNotFoundError()
        return item

    def publish(self, sha256: str) -> ContentItemResponse:
        """Publish (or republish/repair) the public artifact for ``sha256``."""

        item = self._require_item(sha256)
        public_key = self._storage.public_key(sha256)

        # Regenerate from the CANONICAL raw source — re-rendered, never copied
        # from the private preview artifact — so the public copy can never drift
        # from a fresh render of the immutable source.
        raw = self._storage.get_object(item.raw_key)
        if raw is None:
            raise PublishFailedError("The canonical raw source is missing.")
        artifact = render(raw, item.source_type, title=item.original_filename)

        # Always (re)write the public object: it creates the object on a first
        # publish and REPAIRS it when metadata says published but the object is
        # gone. S3 PUT is idempotent for identical content-addressed bytes.
        self._storage.put_public_object(
            public_key, artifact, content_type=_PUBLIC_CONTENT_TYPE
        )

        already_published = (
            item.status is ContentStatus.PUBLISHED
            and item.public_key == public_key
            and item.published_at is not None
        )
        if already_published:
            # Idempotent: object repaired above, metadata already correct.
            return self._response(item)

        now = _iso_ms(self._now())
        published = item.model_copy(
            update={
                "status": ContentStatus.PUBLISHED,
                # Preserve the original publish time across a republish.
                "published_at": item.published_at or now,
                "public_key": public_key,
                "updated_at": now,
            }
        )
        # Both metadata items in one transaction (list sk reuses created_at).
        self._repo.put_content_item(published)
        return self._response(published)

    def unpublish(self, sha256: str) -> ContentItemResponse:
        """Unpublish ``sha256``: delete the public object, invalidate, mark down."""

        item = self._require_item(sha256)
        public_key = item.public_key or self._storage.public_key(sha256)

        # Delete the public object if present (idempotent) ...
        self._storage.delete_public_object(public_key)
        # ... and purge both CloudFront path shapes for the public copy.
        self._invalidator.invalidate(invalidation_paths(sha256))

        already_unpublished = (
            item.status is ContentStatus.UNPUBLISHED
            and item.public_key is None
            and item.published_at is None
        )
        if already_unpublished:
            return self._response(item)

        now = _iso_ms(self._now())
        unpublished = item.model_copy(
            update={
                "status": ContentStatus.UNPUBLISHED,
                "published_at": None,
                "public_key": None,
                "updated_at": now,
            }
        )
        self._repo.put_content_item(unpublished)
        return self._response(unpublished)
