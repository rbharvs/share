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

from share.errors import StorageError

#: ``tmp/`` key prefix for temporary presigned uploads. ``raw/`` and
#: ``artifacts/`` prefixes are introduced by finalize (slice 05).
TMP_PREFIX = "tmp/"

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

    def presign_post(
        self, key: str, *, max_size_bytes: int, expires_in: int = 3600
    ) -> dict[str, Any]:
        """Return a presigned S3 POST (``{"url", "fields"}``) for ``key``."""

    def get_object(self, key: str) -> bytes | None:
        """Return the private-bucket object bytes, or ``None`` if absent."""


class S3ObjectStorage:
    """boto3-backed :class:`ObjectStorage` over the private bucket."""

    def __init__(self, *, client: Any, private_bucket: str) -> None:
        self._client = client
        self._private_bucket = private_bucket

    def tmp_key(self, upload_id: str) -> str:
        return f"{TMP_PREFIX}{upload_id}"

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
