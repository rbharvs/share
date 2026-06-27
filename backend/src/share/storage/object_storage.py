"""S3 object-storage adapter.

A deep module with a small, stable interface that the upload/finalize services
depend on instead of touching boto3 directly. It owns:

- bucket configuration and the ``tmp/`` key helper,
- presigned-POST generation with a ``content-length-range`` size policy,
- a single centralized ``NoSuchKey``/404 → ``None`` translation so callers never
  branch on boto3's exception shapes.

Only the private bucket is needed for the upload vertical; public-bucket
operations arrive with publish (slice 08). The concrete class is injected through
the DI chain so tests substitute a moto-backed (or fake) instance.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from botocore.exceptions import ClientError

from share.content import SourceType
from share.errors import StorageError

#: ``tmp/`` key prefix for temporary presigned uploads.
TMP_PREFIX = "tmp/"

#: ``raw/`` stores the immutable canonical source; ``artifacts/`` stores the
#: authenticated private rendered artifact. Both are SHA-addressed by finalize.
RAW_PREFIX = "raw/"
ARTIFACTS_PREFIX = "artifacts/"

#: ``u/`` is the public-bucket prefix. Publish writes ``u/{sha}/index.html`` so a
#: bare ``/u/{sha}/`` request resolves to the index document at the CDN edge. The
#: shape mirrors the ``/u/{sha}`` private route exactly so the same SHA addresses
#: both the authenticated preview and the published public copy.
PUBLIC_PREFIX = "u/"

#: boto3/S3 error codes that mean "the object is not there" — collapsed to
#: ``None`` rather than surfaced as an error.
_MISSING_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "NotFound", "404"})


def _is_missing(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _MISSING_CODES or status == 404


@runtime_checkable
class ObjectStorage(Protocol):
    """The storage seam the upload services depend on."""

    def tmp_key(self, upload_id: str) -> str:
        """Return the temporary object key for an upload session."""

    def raw_key(self, sha256: str, source_type: SourceType) -> str:
        """Return the canonical raw-source key for a finalized SHA."""

    def artifact_key(self, sha256: str) -> str:
        """Return the private rendered-artifact key for a finalized SHA."""

    def public_key(self, sha256: str) -> str:
        """Return the public-bucket key for a published SHA (``u/{sha}/index.html``)."""

    def put_public_object(
        self, key: str, body: bytes, *, content_type: str | None = None
    ) -> None:
        """Write ``body`` to the public bucket at ``key`` (overwrite).

        Used by publish to write — and repair — the public artifact. Separate
        from :meth:`put_object` so the private and public buckets can never be
        confused at a call site.
        """

    def delete_public_object(self, key: str) -> None:
        """Delete the public-bucket object at ``key`` (idempotent)."""

    def presign_post(
        self, key: str, *, max_size_bytes: int, expires_in: int = 3600
    ) -> dict[str, Any]:
        """Return a presigned S3 POST (``{"url", "fields"}``) for ``key``."""

    def head_size(self, key: str) -> int | None:
        """Return the private-bucket object size in bytes, or ``None`` if absent.

        A ``HEAD`` so the finalize size gate can reject oversize uploads *before*
        downloading their bytes.
        """

    def get_object(self, key: str) -> bytes | None:
        """Return the private-bucket object bytes, or ``None`` if absent."""

    def put_object(
        self, key: str, body: bytes, *, content_type: str | None = None
    ) -> None:
        """Write ``body`` to the private bucket at ``key`` (overwrite)."""

    def delete_object(self, key: str) -> None:
        """Delete the private-bucket object at ``key`` (idempotent)."""


class S3ObjectStorage:
    """boto3-backed :class:`ObjectStorage` over the private and public buckets.

    ``public_bucket`` is optional so the upload vertical (which never touches the
    public bucket) can construct storage without it; the public operations raise
    :class:`StorageError` if invoked when it was not configured.
    """

    def __init__(
        self,
        *,
        client: Any,
        private_bucket: str,
        public_bucket: str | None = None,
    ) -> None:
        self._client = client
        self._private_bucket = private_bucket
        self._public_bucket = public_bucket

    def tmp_key(self, upload_id: str) -> str:
        return f"{TMP_PREFIX}{upload_id}"

    def raw_key(self, sha256: str, source_type: SourceType) -> str:
        return f"{RAW_PREFIX}{sha256}/{source_type.raw_filename}"

    def artifact_key(self, sha256: str) -> str:
        return f"{ARTIFACTS_PREFIX}{sha256}/index.html"

    def public_key(self, sha256: str) -> str:
        return f"{PUBLIC_PREFIX}{sha256}/index.html"

    def _require_public_bucket(self) -> str:
        if self._public_bucket is None:  # pragma: no cover - DI always supplies one.
            raise StorageError("No public bucket configured.")
        return self._public_bucket

    def put_public_object(
        self, key: str, body: bytes, *, content_type: str | None = None
    ) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self._require_public_bucket(),
            "Key": key,
            "Body": body,
        }
        if content_type is not None:
            kwargs["ContentType"] = content_type
        try:
            self._client.put_object(**kwargs)
        except ClientError as exc:
            raise StorageError("Writing the public object failed.") from exc

    def delete_public_object(self, key: str) -> None:
        try:
            self._client.delete_object(
                Bucket=self._require_public_bucket(), Key=key
            )
        except ClientError as exc:
            raise StorageError("Deleting the public object failed.") from exc

    def presign_post(
        self, key: str, *, max_size_bytes: int, expires_in: int = 3600
    ) -> dict[str, Any]:
        """Build a presigned POST whose policy pins the exact key and caps size.

        boto3 auto-adds the exact-``key`` condition (and ``fields['key']``); we
        add the ``content-length-range`` condition so S3 rejects anything over
        the limit at upload time — the first of the two 5 MB size gates.
        """

        return self._client.generate_presigned_post(
            Bucket=self._private_bucket,
            Key=key,
            Conditions=[["content-length-range", 0, max_size_bytes]],
            ExpiresIn=expires_in,
        )

    def head_size(self, key: str) -> int | None:
        try:
            response = self._client.head_object(
                Bucket=self._private_bucket, Key=key
            )
        except ClientError as exc:
            if _is_missing(exc):
                return None
            raise StorageError("Heading the object failed.") from exc
        return int(response["ContentLength"])

    def get_object(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(
                Bucket=self._private_bucket, Key=key
            )
        except ClientError as exc:
            if _is_missing(exc):
                return None
            raise StorageError("Reading the object failed.") from exc
        return response["Body"].read()

    def put_object(
        self, key: str, body: bytes, *, content_type: str | None = None
    ) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self._private_bucket,
            "Key": key,
            "Body": body,
        }
        if content_type is not None:
            kwargs["ContentType"] = content_type
        try:
            self._client.put_object(**kwargs)
        except ClientError as exc:
            raise StorageError("Writing the object failed.") from exc

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._private_bucket, Key=key)
        except ClientError as exc:
            raise StorageError("Deleting the object failed.") from exc
