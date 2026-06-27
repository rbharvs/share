"""DynamoDB metadata repository.

The single-table store behind the upload flow. It brings up the upload-session
half of the interface (``create``/``get``) and the two-item content write that
finalize relies on (slice 05).

Item shapes (PRD single-table design)::

    Upload session:  pk = UPLOAD#{upload_id}      sk = META
    Content lookup:  pk = CONTENT#{sha256}        sk = META
    Content list:    pk = USER#default            sk = CONTENT#{created_at}#{sha256}

Per the spike: use the boto3 *resource* ``Table`` for ``put_item``/``get_item``
(typed-JSON marshalling is handled for us) and the low-level ``client`` for the
finalize ``TransactWriteItems`` — the resource ``Table`` double-serializes typed
JSON and raises ``unhashable type: dict`` under moto. ``size_bytes`` round-trips
low-level ``"N"`` write → resource ``Decimal`` read → Pydantic ``int`` coerce.

The repository is injected through the DI chain so tests substitute a moto-backed
(or fake) instance and never reach AWS.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from botocore.exceptions import ClientError

from share.content import ContentItem, ContentStatus, SourceType
from share.errors import StorageError
from share.upload.models import UploadSession

#: Sort-key value for "the" item of a single-partition entity.
META_SK = "META"

#: Single-workspace partition for the newest-first content list.
USER_LIST_PK = "USER#default"


def _session_pk(upload_id: str) -> str:
    return f"UPLOAD#{upload_id}"


def _content_pk(sha256: str) -> str:
    return f"CONTENT#{sha256}"


def _list_sk(created_at: str, sha256: str) -> str:
    return f"CONTENT#{created_at}#{sha256}"


def _content_attributes(item: ContentItem) -> dict[str, dict[str, Any]]:
    """Marshal the shared content metadata into low-level typed attributes.

    Both the lookup and list items carry this identical block (only ``pk``/``sk``
    differ), so the duplicated metadata is written from one source.
    """

    return {
        "item_type": {"S": "content"},
        "sha256": {"S": item.sha256},
        "source_type": {"S": item.source_type.value},
        "original_filename": {"S": item.original_filename},
        "size_bytes": {"N": str(item.size_bytes)},
        "status": {"S": item.status.value},
        "created_at": {"S": item.created_at},
        "updated_at": {"S": item.updated_at},
        "published_at": (
            {"S": item.published_at}
            if item.published_at is not None
            else {"NULL": True}
        ),
        "created_by": {"S": item.created_by},
        "raw_key": {"S": item.raw_key},
        "private_artifact_key": {"S": item.private_artifact_key},
        "public_key": (
            {"S": item.public_key}
            if item.public_key is not None
            else {"NULL": True}
        ),
        "last_upload_id": {"S": item.last_upload_id},
    }


@runtime_checkable
class MetadataRepository(Protocol):
    """The metadata seam the upload services depend on."""

    def create_upload_session(self, session: UploadSession) -> None:
        """Persist a new upload session (idempotent overwrite by id)."""

    def get_upload_session(self, upload_id: str) -> UploadSession | None:
        """Load an upload session by id, or ``None`` if absent."""

    def get_content_item(self, sha256: str) -> ContentItem | None:
        """Load a finalized content item by SHA, or ``None`` if absent.

        The dedupe source of truth at finalize — reads the canonical lookup
        item, never an S3 ``raw_exists`` probe (a crashed prior finalize could
        otherwise falsely dedupe).
        """

    def put_content_item(self, item: ContentItem) -> None:
        """Write both content metadata items in one atomic transaction.

        The lookup item (``CONTENT#{sha}/META``) and the newest-first list item
        (``USER#default/CONTENT#{created_at}#{sha}``) carry identical metadata and
        are written via a single ``TransactWriteItems`` so they can never drift.
        """


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

    def get_content_item(self, sha256: str) -> ContentItem | None:
        try:
            response = self._table.get_item(
                Key={"pk": _content_pk(sha256), "sk": META_SK}
            )
        except ClientError as exc:
            raise StorageError("Reading the content item failed.") from exc

        item = response.get("Item")
        if not item:
            return None

        return ContentItem(
            sha256=item["sha256"],
            source_type=SourceType.parse(item["source_type"]),
            original_filename=item["original_filename"],
            # "N" write -> resource Decimal read -> Pydantic int coerce.
            size_bytes=item["size_bytes"],
            status=ContentStatus.parse(item["status"]),
            created_at=item["created_at"],
            updated_at=item["updated_at"],
            published_at=item.get("published_at"),
            created_by=item["created_by"],
            raw_key=item["raw_key"],
            private_artifact_key=item["private_artifact_key"],
            public_key=item.get("public_key"),
            last_upload_id=item["last_upload_id"],
        )

    def put_content_item(self, item: ContentItem) -> None:
        if self._client is None:  # pragma: no cover - DI always supplies one.
            raise StorageError("No low-level DynamoDB client configured.")

        shared = _content_attributes(item)
        lookup = {
            "pk": {"S": _content_pk(item.sha256)},
            "sk": {"S": META_SK},
            **shared,
        }
        listing = {
            "pk": {"S": USER_LIST_PK},
            "sk": {"S": _list_sk(item.created_at, item.sha256)},
            **shared,
        }
        try:
            # Low-level client: the resource Table double-serializes typed JSON
            # and raises "unhashable type: dict" under moto (spike-confirmed).
            self._client.transact_write_items(
                TransactItems=[
                    {"Put": {"TableName": self._table_name, "Item": lookup}},
                    {"Put": {"TableName": self._table_name, "Item": listing}},
                ]
            )
        except ClientError as exc:
            raise StorageError("Writing the content item failed.") from exc
