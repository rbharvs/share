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

import os
from enum import Enum

from share.errors import UnsupportedSourceTypeError

#: Filename-extension hints. The canonical extension drives source-type when the
#: owner does not supply an explicit override.
_EXTENSION_HINTS: dict[str, str] = {
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
}

#: MIME-type hints, used only when the filename extension is uninformative.
_MIME_HINTS: dict[str, str] = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
}


class SourceType(str, Enum):
    """The kind of a finalized upload's canonical raw source."""

    HTML = "html"
    MARKDOWN = "markdown"

    @property
    def raw_filename(self) -> str:
        """The canonical stored filename for this source type's raw object."""

        return "source.html" if self is SourceType.HTML else "source.md"

    @classmethod
    def infer(
        cls,
        *,
        filename: str,
        content_type: str | None = None,
        override: str | SourceType | None = None,
    ) -> SourceType:
        """Resolve the source type at upload time.

        Precedence: explicit owner ``override`` wins; otherwise the filename
        extension; otherwise the declared ``content_type``. Anything that cannot
        be resolved to a v1-supported type raises
        :class:`UnsupportedSourceTypeError` (the ``unsupported_source_type``
        PRD code), so the value stored on the session is always valid.
        """

        if isinstance(override, cls):
            return override
        if override is not None and override.strip():
            return cls.parse(override)

        ext = os.path.splitext(filename or "")[1].strip().lower()
        if ext in _EXTENSION_HINTS:
            return cls(_EXTENSION_HINTS[ext])

        if content_type:
            mime = content_type.split(";", 1)[0].strip().lower()
            if mime in _MIME_HINTS:
                return cls(_MIME_HINTS[mime])

        raise UnsupportedSourceTypeError(
            f"Could not infer a supported source type for {filename!r}."
        )

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
