"""The upload service — the deep module behind the upload APIs.

It implements two verticals:

* ``presign`` — infer the source type, mint an upload id, write a TTL'd session
  item carrying the verified ``created_by`` (anti-spoof anchor), and return a
  presigned S3 POST whose policy caps the size at 5 MB and pins the
  ``tmp/{upload_id}`` key.
* ``finalize`` — turn a completed temp upload into an immutable, SHA-addressed
  content item. Strict ordering keeps a mid-finalize crash retryable and never
  strands state: ``validate → SHA → metadata-dedupe → raw-put-if-missing →
  artifact → upsert BOTH items atomically → delete temp LAST``. Filename, source
  type, and title come *only* from the stored session — never the request body.

The service depends only on the :class:`ObjectStorage` and
:class:`MetadataRepository` seams (plus an injectable clock / id factory for
deterministic tests) — never on boto3 or FastAPI.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from share.auth import Principal
from share.content import (
    MAX_UPLOAD_BYTES,
    ContentItem,
    ContentItemResponse,
    ContentStatus,
    SourceType,
)
from share.errors import (
    InvalidUtf8Error,
    UploadExpiredError,
    UploadNotFoundError,
    UploadNotUploadedError,
    UploadTooLargeError,
)
from share.renderer import render
from share.repository import MetadataRepository
from share.storage import ObjectStorage

from .models import (
    FinalizeRequest,
    PresignRequest,
    PresignResponse,
    UploadSession,
)

#: Upload-session lifetime — the DynamoDB TTL window for abandoned sessions.
SESSION_TTL_SECONDS = 3600

#: Per-source-type content type for the stored raw object.
_RAW_CONTENT_TYPES: dict[SourceType, str] = {
    SourceType.HTML: "text/html; charset=utf-8",
    SourceType.MARKDOWN: "text/markdown; charset=utf-8",
}

#: The rendered private artifact is always an HTML document.
_ARTIFACT_CONTENT_TYPE = "text/html; charset=utf-8"


def _iso(epoch: float) -> str:
    """Format unix-seconds as a ``Z``-suffixed UTC ISO-8601 timestamp."""

    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _iso_ms(epoch: float) -> str:
    """Format unix-seconds as a millisecond-resolution UTC ISO-8601 timestamp.

    Content ``created_at`` drives the list sort key, so millisecond resolution
    keeps same-second uploads ordered deterministically by insertion rather than
    colliding on a one-second bucket.
    """

    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}.{dt.microsecond // 1000:03d}Z"


class UploadService:
    """Coordinates upload sessions, S3 presigning, and metadata persistence."""

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        repo: MetadataRepository,
        private_host: str = "private.usercontent.example",
        public_host: str = "public.usercontent.example",
        now_fn: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._storage = storage
        self._repo = repo
        self._private_host = private_host
        self._public_host = public_host
        self._now = now_fn
        self._new_id = id_factory

    def _response(self, item: ContentItem) -> ContentItemResponse:
        return ContentItemResponse.from_item(
            item,
            private_host=self._private_host,
            public_host=self._public_host,
        )

    def presign(
        self, request: PresignRequest, principal: Principal
    ) -> PresignResponse:
        """Create a session and return a presigned S3 POST for the upload."""

        source_type: SourceType = SourceType.infer(
            filename=request.filename,
            content_type=request.content_type,
            override=request.source_type,
        )

        upload_id = self._new_id()
        key = self._storage.tmp_key(upload_id)
        now = self._now()

        session = UploadSession(
            upload_id=upload_id,
            created_by=principal.email,
            original_filename=request.filename,
            source_type=source_type,
            title=request.title,
            tmp_key=key,
            max_size_bytes=MAX_UPLOAD_BYTES,
            created_at=_iso(now),
            expires_at_epoch=int(now) + SESSION_TTL_SECONDS,
        )
        self._repo.create_upload_session(session)

        presigned = self._storage.presign_post(
            key, max_size_bytes=MAX_UPLOAD_BYTES, expires_in=SESSION_TTL_SECONDS
        )

        return PresignResponse(
            upload_id=upload_id,
            url=presigned["url"],
            fields=presigned["fields"],
            max_size_bytes=MAX_UPLOAD_BYTES,
        )

    def finalize(
        self, request: FinalizeRequest, principal: Principal
    ) -> ContentItemResponse:
        """Turn a completed temp upload into an immutable content item.

        Ordering is load-bearing — ``validate → SHA → metadata-dedupe →
        raw-put-if-missing → artifact → upsert BOTH items atomically → delete
        temp LAST`` — so a crash at any step leaves the temp object intact and
        the finalize is safely retryable.
        """

        session = self._repo.get_upload_session(request.upload_id)
        if session is None:
            raise UploadNotFoundError()
        if self._now() >= session.expires_at_epoch:
            raise UploadExpiredError()

        # Head-size gate BEFORE download: reject oversize (and absent) temp
        # objects without ever pulling their bytes into memory.
        size = self._storage.head_size(session.tmp_key)
        if size is None:
            raise UploadNotUploadedError()
        if size > session.max_size_bytes:
            raise UploadTooLargeError()

        raw = self._storage.get_object(session.tmp_key)
        if raw is None:  # Raced deletion between head and get.
            raise UploadNotUploadedError()

        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidUtf8Error() from exc

        # SHA-256 over the raw uploaded bytes, before any normalization.
        sha256 = hashlib.sha256(raw).hexdigest()

        # Dedupe off metadata (the source of truth), NOT an S3 raw_exists probe:
        # a crashed prior finalize that wrote raw but no metadata must NOT dedupe.
        existing = self._repo.get_content_item(sha256)
        if existing is not None:
            self._storage.delete_object(session.tmp_key)  # temp deleted LAST.
            return self._response(existing)

        # raw-put (idempotent: content-addressed, so identical on retry) ...
        raw_key = self._storage.raw_key(sha256, session.source_type)
        self._storage.put_object(
            raw_key,
            raw,
            content_type=_RAW_CONTENT_TYPES[session.source_type],
        )

        # ... then the rendered private artifact. Title comes from the SESSION's
        # original filename, never the request body.
        artifact = render(
            raw, session.source_type, title=session.original_filename
        )
        artifact_key = self._storage.artifact_key(sha256)
        self._storage.put_object(
            artifact_key, artifact, content_type=_ARTIFACT_CONTENT_TYPE
        )

        created_at = _iso_ms(self._now())
        item = ContentItem(
            sha256=sha256,
            source_type=session.source_type,
            original_filename=session.original_filename,
            size_bytes=len(raw),
            status=ContentStatus.UPLOADED,
            created_at=created_at,
            updated_at=created_at,
            published_at=None,
            created_by=session.created_by,
            raw_key=raw_key,
            private_artifact_key=artifact_key,
            public_key=None,
            last_upload_id=session.upload_id,
        )
        # Both metadata items in one transaction ...
        self._repo.put_content_item(item)
        # ... and only now is the temp object safe to remove.
        self._storage.delete_object(session.tmp_key)

        return self._response(item)
