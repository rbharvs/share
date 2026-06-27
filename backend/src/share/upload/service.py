"""The upload service — the deep module behind the upload APIs.

This slice implements ``presign``: infer the source type, mint an upload id,
write a TTL'd session item carrying the verified ``created_by`` (anti-spoof
anchor), and return a presigned S3 POST whose policy caps the size at 5 MB and
pins the ``tmp/{upload_id}`` key. ``finalize`` lands in slice 05.

The service depends only on the :class:`ObjectStorage` and
:class:`MetadataRepository` seams (plus an injectable clock / id factory for
deterministic tests) — never on boto3 or FastAPI.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from share.auth import Principal
from share.content import MAX_UPLOAD_BYTES, SourceType
from share.repository import MetadataRepository
from share.storage import ObjectStorage

from .models import PresignRequest, PresignResponse, UploadSession

#: Upload-session lifetime — the DynamoDB TTL window for abandoned sessions.
SESSION_TTL_SECONDS = 3600


def _iso(epoch: float) -> str:
    """Format unix-seconds as a ``Z``-suffixed UTC ISO-8601 timestamp."""

    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


class UploadService:
    """Coordinates upload sessions, S3 presigning, and metadata persistence."""

    def __init__(
        self,
        *,
        storage: ObjectStorage,
        repo: MetadataRepository,
        now_fn: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._storage = storage
        self._repo = repo
        self._now = now_fn
        self._new_id = id_factory

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
