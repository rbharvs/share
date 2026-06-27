"""Pure host/path/method gate.

Zero FastAPI imports — this is a string-only decision function covered by
string-table unit tests. It encapsulates all host-based route security rules:

    | Host kind        | Allowed                                                |
    | ---------------- | ------------------------------------------------------ |
    | dashboard        | SPA/assets/robots + ``/api/*`` (SPA fallback handles   |
    |                  | unknown browser paths; routing/404/405 decide the rest)|
    |                  | but NOT ``/u/{sha}`` -> ``route_not_allowed`` (uploaded |
    |                  | content must never be served same-origin as dashboard) |
    | private-content  | root, robots, ``GET``/``HEAD`` ``/u/{sha}`` only       |
    |                  | dashboard APIs -> ``route_not_allowed``                |
    | public-content   | always ``403 host_not_allowed`` (must never reach      |
    |                  | Lambda)                                                |
    | unknown          | ``403 host_not_allowed``                               |

For the dashboard the gate only enforces the host boundary; whether an unknown
path or unsupported method is a ``route_not_allowed`` is decided by FastAPI
routing (404/405), mapped centrally to the same error code.
"""

from __future__ import annotations

import re

from share.errors import HostNotAllowedError, RouteNotAllowedError
from share.hosts import HostKind, classify_host

_READ_METHODS = frozenset({"GET", "HEAD"})

#: ``/u/{sha256}`` with an optional trailing slash. SHA validity is enforced by
#: route handlers in later slices; the gate only recognises the shape.
_CONTENT_PATH = re.compile(r"^/u/[^/]+/?$")


def _is_private_content_allowed(path: str, method: str) -> bool:
    """Private content host: root, robots, and content reads only."""

    if method not in _READ_METHODS:
        return False
    if path in ("/", "/robots.txt"):
        return True
    return bool(_CONTENT_PATH.match(path))


def evaluate(
    host: str | None,
    path: str,
    method: str,
    *,
    host_kinds: dict[str, HostKind] | None = None,
) -> HostKind:
    """Decide whether ``(host, path, method)`` is allowed.

    Returns the resolved :class:`HostKind` when allowed, or raises a
    :class:`~share.errors.ShareError`:

    - :class:`~share.errors.HostNotAllowedError` for public/unknown hosts.
    - :class:`~share.errors.RouteNotAllowedError` for routes disallowed on the
      private content host.
    """

    kind = classify_host(host, host_kinds)
    method = method.upper()

    if kind is HostKind.DASHBOARD:
        # Uploaded content must never be served from the dashboard origin (it
        # would render same-origin with the dashboard — the XSS scenario the
        # host separation defends against). The content-by-sha shape is only
        # valid on the content hosts; reject it here even though the route is
        # registered, before it can reach the handler.
        if _CONTENT_PATH.match(path):
            raise RouteNotAllowedError()
        return kind

    if kind is HostKind.PRIVATE_CONTENT:
        if _is_private_content_allowed(path, method):
            return kind
        raise RouteNotAllowedError()

    # public-content (must never reach Lambda) and unknown hosts.
    raise HostNotAllowedError()
