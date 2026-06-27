"""The finalized content item: the immutable, SHA-addressed unit of the service.

This module carries the two related shapes that finalize, list, publish, and
unpublish all share:

* :class:`ContentItem` — the persisted domain object mirroring the PRD metadata
  fields. It is the source of truth duplicated across the DynamoDB lookup item
  (``CONTENT#{sha}/META``) and list item (``USER#default/CONTENT#{created_at}#{sha}``).
* :class:`ContentItemResponse` — the *common content item response* every content
  API returns. It is derived from a :class:`ContentItem` plus the configured
  content hosts, so private/public URLs are built in one place.

Like the rest of the ``content`` package this module is pure: Pydantic models and
a value enum, no IO and no AWS imports.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from share.errors import UnsupportedSourceTypeError

from .source_type import SourceType

#: Length of the abbreviated SHA shown in the dashboard ("first-12ish chars").
SHORT_SHA_LEN = 12


class ContentStatus(str, Enum):
    """Lifecycle state of a finalized content item.

    Finalized uploads start as :attr:`UPLOADED`; publish/unpublish (slice 08)
    move between :attr:`PUBLISHED` and :attr:`UNPUBLISHED`.
    """

    UPLOADED = "uploaded"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"

    @classmethod
    def parse(cls, value: str) -> ContentStatus:
        """Coerce a stored status string into the enum, tolerantly."""

        try:
            return cls(value.strip().lower())
        except (ValueError, AttributeError) as exc:  # pragma: no cover - defensive
            raise UnsupportedSourceTypeError(
                f"Unsupported content status: {value!r}."
            ) from exc


class ContentItem(BaseModel):
    """Persisted content metadata (the PRD ``Content metadata fields``).

    Immutable once written: a re-finalize of identical bytes dedupes to the
    existing item rather than mutating it. ``public_key``/``published_at`` are
    ``None`` until the item is published.
    """

    model_config = ConfigDict(frozen=True)

    sha256: str
    source_type: SourceType
    original_filename: str
    size_bytes: int
    status: ContentStatus
    created_at: str
    updated_at: str
    published_at: str | None = None
    created_by: str
    raw_key: str
    private_artifact_key: str
    public_key: str | None = None
    last_upload_id: str


class ContentItemResponse(BaseModel):
    """The common content-item API representation returned by every content API.

    Built from a :class:`ContentItem` plus the configured content hosts so the
    private/public URLs are constructed in exactly one place. ``public_url`` is
    ``None`` unless the item is published.
    """

    sha256: str
    short_sha: str
    source_type: SourceType
    original_filename: str
    size_bytes: int
    status: ContentStatus
    created_at: str
    updated_at: str
    published_at: str | None
    private_url: str
    public_url: str | None

    @classmethod
    def from_item(
        cls, item: ContentItem, *, private_host: str, public_host: str
    ) -> ContentItemResponse:
        """Project a domain :class:`ContentItem` onto the common API response."""

        published = item.status is ContentStatus.PUBLISHED
        return cls(
            sha256=item.sha256,
            short_sha=item.sha256[:SHORT_SHA_LEN],
            source_type=item.source_type,
            original_filename=item.original_filename,
            size_bytes=item.size_bytes,
            status=item.status,
            created_at=item.created_at,
            updated_at=item.updated_at,
            published_at=item.published_at,
            private_url=f"https://{private_host}/u/{item.sha256}",
            public_url=(
                f"https://{public_host}/u/{item.sha256}" if published else None
            ),
        )
