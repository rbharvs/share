"""DynamoDB metadata repository.

The single-table store behind the upload flow. This slice brings up the
upload-session half of the interface (``create``/``get``); the two-item content
write (``TransactWriteItems``) arrives with finalize (slice 05).

Item shape (PRD single-table design)::

    Upload session:  pk = UPLOAD#{upload_id}   sk = META

Per the spike: use the boto3 *resource* ``Table`` for ``put_item``/``get_item``
(typed-JSON marshalling is handled for us) and reserve the low-level client for
the finalize transaction. The repository is injected through the DI chain so
tests substitute a moto-backed (or fake) instance and never reach AWS.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from botocore.exceptions import ClientError

from share.content import SourceType
from share.errors import StorageError
from share.upload.models import UploadSession

#: Sort-key value for "the" item of a single-partition entity.
META_SK = "META"


def _session_pk(upload_id: str) -> str:
    return f"UPLOAD#{upload_id}"


@runtime_checkable
class MetadataRepository(Protocol):
    """The metadata seam the upload services depend on."""

    def create_upload_session(self, session: UploadSession) -> None:
        """Persist a new upload session (idempotent overwrite by id)."""

    def get_upload_session(self, upload_id: str) -> UploadSession | None:
        """Load an upload session by id, or ``None`` if absent."""


class DynamoMetadataRepository:
    """boto3-backed :class:`MetadataRepository`."""

    def __init__(
        self,
        *,
        table_name: str,
        resource: Any,
        client: Any | None = None,
    ) -> None:
        self._table_name = table_name
        self._table = resource.Table(table_name)
        # Reserved for the finalize TransactWriteItems (slice 05).
        self._client = client

    def create_upload_session(self, session: UploadSession) -> None:
        item: dict[str, Any] = {
            "pk": _session_pk(session.upload_id),
            "sk": META_SK,
            "item_type": "upload_session",
            "upload_id": session.upload_id,
            "created_by": session.created_by,
            "original_filename": session.original_filename,
            "source_type": session.source_type.value,
            "tmp_key": session.tmp_key,
            "max_size_bytes": session.max_size_bytes,
            "created_at": session.created_at,
            "expires_at_epoch": session.expires_at_epoch,
        }
        if session.title is not None:
            item["title"] = session.title
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise StorageError("Writing the upload session failed.") from exc

    def get_upload_session(self, upload_id: str) -> UploadSession | None:
        try:
            response = self._table.get_item(
                Key={"pk": _session_pk(upload_id), "sk": META_SK}
            )
        except ClientError as exc:
            raise StorageError("Reading the upload session failed.") from exc

        item = response.get("Item")
        if not item:
            return None

        return UploadSession(
            upload_id=item["upload_id"],
            created_by=item["created_by"],
            original_filename=item["original_filename"],
            # DynamoDB hands back numbers as Decimal; Pydantic coerces to int.
            source_type=SourceType.parse(item["source_type"]),
            title=item.get("title"),
            tmp_key=item["tmp_key"],
            max_size_bytes=int(item["max_size_bytes"]),
            created_at=item["created_at"],
            expires_at_epoch=int(item["expires_at_epoch"]),
        )
