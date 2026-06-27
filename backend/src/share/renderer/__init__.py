"""The content renderer.

Public surface is intentionally tiny: the frozen ``render`` function and the
``Renderer`` protocol it dispatches to. :class:`SourceType` is re-exported for
callers that already hold a renderer import.
"""

from share.content import SourceType

from .renderer import (
    HtmlPassthroughRenderer,
    MarkdownShellRenderer,
    Renderer,
    render,
)

__all__ = [
    "HtmlPassthroughRenderer",
    "MarkdownShellRenderer",
    "Renderer",
    "SourceType",
    "render",
]
