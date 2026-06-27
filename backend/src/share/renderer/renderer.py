"""The content renderer: raw source bytes + source type -> artifact bytes.

``render(raw, source_type, *, title) -> bytes`` is a single, pure funnel with a
**frozen** signature. Finalize (slice 05) calls it to produce the private
artifact and publish (slice 08) calls it *verbatim* to regenerate the public
artifact from the canonical raw source, so private preview and public output can
never diverge. Because of that contract this module is deliberately pure: it has
zero AWS and zero IO imports, takes only bytes + a value object + a title, and
returns bytes.

Dispatch is a ``match``/``assert_never`` factory over :class:`SourceType`, so
adding a future source type is a compile-time-exhaustive change rather than a
silent fall-through. The two behaviors are intentionally asymmetric:

* **HTML** is returned byte-for-byte — no sanitize, no wrap, no injected title,
  metadata, scripts, or styles. The exact uploaded bytes *are* the artifact.
* **Markdown** is rendered through ``wenmode`` configured for unsafe/raw
  preservation (raw HTML, ``javascript:`` URLs, ``onclick=`` attributes, and
  GFM tables / task-lists / strikethrough all survive) and wrapped in the
  standalone HTML shell, using the caller-supplied filename as ``<title>``.
"""

from __future__ import annotations

from typing import Protocol, assert_never

from wenmode import HTMLRenderer, Wenmode, presets

from share.content import SourceType

from .shell import wrap_document

#: ``wenmode`` configured to preserve unsafe/raw behavior, per the PRD rendering
#: requirements. ``escape=False`` keeps raw HTML; ``sanitize_urls=False`` keeps
#: ``javascript:`` URLs; ``sanitize_attrs=False`` keeps ``onclick=`` and friends.
#: ``presets.github`` enables GFM tables, task lists, and strikethrough. Built
#: once at import; ``wenmode`` is pinned in the lockfile so output is stable.
_WENMODE = Wenmode(
    rules=presets.github,
    renderer=HTMLRenderer(escape=False, sanitize_urls=False, sanitize_attrs=False),
)


class Renderer(Protocol):
    """Render one source type's raw bytes into artifact bytes.

    ``title`` is the original upload filename, supplied only by the caller (the
    upload session); it is never trusted from a finalize request body.
    """

    def render(self, raw: bytes, *, title: str) -> bytes: ...


class HtmlPassthroughRenderer:
    """HTML: the uploaded bytes *are* the artifact, returned byte-for-byte.

    No sanitize, no wrap, no injected title/metadata/scripts/styles. ``title``
    is ignored because an HTML upload carries its own ``<title>`` (if any).
    """

    def render(self, raw: bytes, *, title: str) -> bytes:
        return raw


class MarkdownShellRenderer:
    """Markdown: render through ``wenmode`` and wrap in the document shell."""

    def __init__(self, wenmode: Wenmode = _WENMODE) -> None:
        self._wenmode = wenmode

    def render(self, raw: bytes, *, title: str) -> bytes:
        # Callers pass canonical raw source that finalize already validated as
        # UTF-8; decode strictly so any contract violation is loud, not silent.
        text = raw.decode("utf-8")
        body_html = self._wenmode.render(text)
        document = wrap_document(body_html, title=title)
        return document.encode("utf-8")


def _renderer_for(source_type: SourceType) -> Renderer:
    """Select the renderer for a source type, exhaustively over the enum."""

    match source_type:
        case SourceType.HTML:
            return HtmlPassthroughRenderer()
        case SourceType.MARKDOWN:
            return MarkdownShellRenderer()
        case _:  # pragma: no cover - exhaustive over SourceType
            assert_never(source_type)


def render(raw: bytes, source_type: SourceType, *, title: str) -> bytes:
    """Render raw source bytes into rendered artifact bytes.

    The frozen public interface of this slice, reused unchanged by finalize and
    publish so private and public artifacts are produced by identical code.
    """

    return _renderer_for(source_type).render(raw, title=title)
