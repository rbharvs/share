"""Listing-vertical API models.

The response is the paginated wrapper around the *common content-item response*:
a newest-first page of items plus the opaque cursor for the next page
(``None`` once the listing is exhausted).
"""

from __future__ import annotations

from pydantic import BaseModel

from share.content import ContentItemResponse

#: Default page size when the request omits ``limit`` (PRD: 50).
DEFAULT_LIST_LIMIT = 50

#: Upper bound on a single page, so one request can never pull the whole table.
MAX_LIST_LIMIT = 100


class ContentListResponse(BaseModel):
    """A newest-first page of content items plus the next opaque cursor."""

    items: list[ContentItemResponse]
    next_cursor: str | None
