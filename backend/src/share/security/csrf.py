"""CSRF + Origin guard for unsafe dashboard methods.

Browsers attach ``Origin`` on cross-site requests and forbid setting custom
headers cross-origin without a passing CORS preflight. Because v1 ships NO CORS
middleware, requiring a custom ``X-Share-CSRF: 1`` header AND an exact-match
``Origin`` means a malicious page (or sandboxed uploaded content) cannot forge a
state-changing dashboard call: it can neither set the custom header nor present
the dashboard origin.

The accepted origin comes from the per-app :class:`Settings` (prod vs. local are
swapped wholesale), read off ``app.state`` — the same DI seam the verifier uses.
Either failure raises :class:`ValidationError`, mapping to ``validation_error``.
"""

from __future__ import annotations

from fastapi import Request

from share.config import Settings, get_settings
from share.errors import ValidationError

#: The custom header dashboard mutations must carry. A literal sentinel value;
#: it is not a secret, it exists to require a header a cross-origin page cannot
#: set without a (absent) CORS preflight.
CSRF_HEADER = "X-Share-CSRF"
CSRF_TOKEN = "1"


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


def require_csrf(request: Request) -> None:
    """Reject unsafe dashboard requests lacking the CSRF header / dashboard
    origin."""

    if request.headers.get(CSRF_HEADER) != CSRF_TOKEN:
        raise ValidationError("Missing or invalid CSRF header.")

    expected_origin = _settings(request).dashboard_origin
    if request.headers.get("origin") != expected_origin:
        raise ValidationError("Request origin is not allowed.")
