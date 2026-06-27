"""Upload-vertical Pydantic models: the API request/response and the stored
upload-session domain object.

The session is the anti-spoof anchor of the upload flow: ``created_by``,
``original_filename``, ``source_type`` and ``title`` are decided here at presign
time from the verified principal and the inferred type, written to DynamoDB, and
read back verbatim at finalize (slice 05). The finalize request body never gets
to re-assert any of them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from share.content import SourceType


class PresignRequest(BaseModel):
    """Dashboard presign request body."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=512)
    content_type: str | None = None
    #: Explicit owner override; when absent the type is inferred from filename.
    source_type: SourceType | None = None
    #: Optional display title; defaults to the filename at finalize.
    title: str | None = None


class FinalizeRequest(BaseModel):
    """Dashboard finalize request body.

    Deliberately carries *only* the ``upload_id``: filename, source type, and
    title are read from the stored upload session, never re-asserted here
    (``extra="forbid"`` rejects any attempt to smuggle them in).
    """

    model_config = ConfigDict(extra="forbid")

    upload_id: str = Field(min_length=1)


class PresignResponse(BaseModel):
    """Dashboard presign response.

    ``url``/``fields`` are passed straight to the browser, which POSTs the file
    directly to S3. The exact ``fields`` depend on boto3's presigned-POST output.
    """

    upload_id: str
    url: str
    fields: dict[str, str]
    max_size_bytes: int


class UploadSession(BaseModel):
    """A temporary upload session, persisted with a ~1h DynamoDB TTL.

    ``expires_at_epoch`` is the unix-seconds TTL attribute DynamoDB uses to reap
    abandoned sessions; finalize additionally treats a past value as
    ``upload_expired`` (slice 05) without relying on DynamoDB's lazy deletion.
    """

    model_config = ConfigDict(frozen=True)

    upload_id: str
    created_by: str
    original_filename: str
    source_type: SourceType
    title: str | None = None
    tmp_key: str
    max_size_bytes: int
    created_at: str
    expires_at_epoch: int
