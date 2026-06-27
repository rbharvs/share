"""The content-listing service — the deep module behind ``GET /api/content``.

It owns the read-side of the content library: decode the incoming opaque cursor,
ask the repository for one newest-first page of the ``USER#default`` partition,
project each domain :class:`ContentItem` onto the common content-item response
(building ``private_url`` always, ``public_url`` only when published), and re-wrap
the repository's pagination token as the next opaque cursor.

Ordering is the repository's responsibility (the ``CONTENT#{created_at}#{sha}``
sort key, descending). With millisecond ``created_at`` (slice 05) insertion order
is preserved; same-millisecond uploads tie-break on SHA — documented, stable
behavior that exactly matches the list sort key.

The service depends only on the :class:`MetadataRepository` seam and two host
strings — never on boto3 or FastAPI — so tests drive it against a fake or
moto-backed repository.
"""

from __future__ import annotations

from share.content import ContentItemResponse
from share.repository import MetadataRepository

from .cursor import decode_cursor, encode_cursor
from .models import ContentListResponse


class ContentService:
    """Reads newest-first pages of the content library for the dashboard."""

    def __init__(
        self,
        *,
        repo: MetadataRepository,
        private_host: str = "private.usercontent.example",
        public_host: str = "public.usercontent.example",
    ) -> None:
        self._repo = repo
        self._private_host = private_host
        self._public_host = public_host

    def list_content(
        self, *, limit: int, cursor: str | None = None
    ) -> ContentListResponse:
        """Return one newest-first page of content items and the next cursor.

        ``cursor`` (when present) is the opaque token from the previous page; it
        decodes to the DynamoDB ``ExclusiveStartKey`` so the page resumes without
        scanning or re-reading earlier items. ``next_cursor`` is ``None`` once the
        listing is exhausted.
        """

        start_key = decode_cursor(cursor) if cursor else None
        page = self._repo.list_content(limit=limit, start_key=start_key)

        items = [
            ContentItemResponse.from_item(
                item,
                private_host=self._private_host,
                public_host=self._public_host,
            )
            for item in page.items
        ]
        next_cursor = (
            encode_cursor(page.last_evaluated_key)
            if page.last_evaluated_key is not None
            else None
        )
        return ContentListResponse(items=items, next_cursor=next_cursor)
