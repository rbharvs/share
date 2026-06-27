"""The source-type domain primitive.

A finalized upload is either raw ``html`` or ``markdown``. The value is decided
once at upload time (inferred from filename / MIME, with an explicit owner
override) and then stored on the upload session. Every later step — finalize
(slice 05) and publish (slice 08) — reads the *stored* source type; it is never
re-derived from, or trusted out of, a request body.

This is a small, stable schema primitive shared by the renderer, the upload
service, and the content metadata model. It carries no IO and no AWS imports.
"""

from __future__ import annotations

from enum import Enum

from share.errors import UnsupportedSourceTypeError


class SourceType(str, Enum):
    """The kind of a finalized upload's canonical raw source."""

    HTML = "html"
    MARKDOWN = "markdown"

    @classmethod
    def parse(cls, value: str) -> SourceType:
        """Coerce a stored/string source type into the enum.

        Raises :class:`UnsupportedSourceTypeError` for anything not in the v1
        supported set, mapping straight onto the ``unsupported_source_type``
        PRD error code. Matching is case-insensitive and whitespace-tolerant
        so values that survived a round-trip through storage still resolve.
        """

        try:
            return cls(value.strip().lower())
        except (ValueError, AttributeError) as exc:
            raise UnsupportedSourceTypeError(
                f"Unsupported source type: {value!r}."
            ) from exc
