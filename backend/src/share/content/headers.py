"""Rendered-content response headers — the load-bearing isolation defense.

Serving arbitrary uploaded HTML/JS safely depends on one header above all: the
``Content-Security-Policy: sandbox`` *without* ``allow-same-origin``. That single
directive forces every rendered artifact into an opaque origin, so uploaded
scripts can never reach cookies, storage, or same-origin requests against the
dashboard. The remaining headers (``nosniff`` / ``no-referrer`` /
``noindex,nofollow``) harden sniffing, referrer leakage, and indexing.

This module is the single source of truth for that header set. The private
content host (slice 07) emits :func:`private_rendered_headers`; the public
CloudFront response-headers policy (slice 13) must reproduce
:data:`SHARED_SECURITY_HEADERS` byte-for-byte and is cross-checked against these
constants. Only the cache directive differs between the two hosts: private
content is ``no-store`` (authenticated, never cached); public content is cached
at the edge.

Pure data — no IO, no AWS, no FastAPI — so it is importable from anywhere
(handlers, tests, and the infra cross-check).
"""

from __future__ import annotations

#: The rendered artifact is always a full HTML document.
RENDERED_CONTENT_TYPE = "text/html; charset=utf-8"

#: The CSP sandbox. ``allow-same-origin`` is deliberately ABSENT — re-adding it
#: would collapse the opaque-origin isolation and is the one change that must
#: never be made here.
RENDERED_CONTENT_CSP = "sandbox allow-scripts allow-forms allow-popups allow-downloads"

#: Security headers shared byte-for-byte by every rendered-content host (private
#: now, public via the slice-13 CloudFront policy). Order is stable so the infra
#: cross-check can compare the mapping directly.
SHARED_SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": RENDERED_CONTENT_CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


def private_rendered_headers() -> dict[str, str]:
    """Build the full header set for an authenticated private rendered artifact.

    Returns a fresh dict (handlers mutate it to add ``Content-Length``) carrying
    the content type, the shared security headers, and the private-only
    ``Cache-Control: no-store``.
    """

    return {
        "Content-Type": RENDERED_CONTENT_TYPE,
        **SHARED_SECURITY_HEADERS,
        "Cache-Control": "no-store",
    }
