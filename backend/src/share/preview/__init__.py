"""The private-preview vertical: authenticated rendered-artifact reads.

Serves ``GET``/``HEAD /u/{sha}`` on the private content host — the read-only
counterpart to finalize, returning the stored private rendered artifact behind
the CSP-sandbox header set.
"""

from .dependencies import PreviewServiceDep, get_preview_service
from .service import PreviewService

__all__ = [
    "PreviewService",
    "PreviewServiceDep",
    "get_preview_service",
]
