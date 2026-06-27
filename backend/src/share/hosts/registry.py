"""Shared host registry.

One ``classify_host(raw_host) -> HostKind`` keyed by exact strings. Routes and
middleware never read the ``Host`` header directly: this is the single adapter
for any future ``X-Forwarded-Host`` / CloudFront ingress change.
"""

from __future__ import annotations

from enum import Enum


class HostKind(str, Enum):
    """The security class of an incoming host."""

    DASHBOARD = "dashboard"
    PRIVATE_CONTENT = "private-content"
    PUBLIC_CONTENT = "public-content"
    UNKNOWN = "unknown"


#: Production host strings, mapped to their security class. This is the ONLY
#: mapping that may ever be served in production.
PROD_HOST_KINDS: dict[str, HostKind] = {
    "share.example.com": HostKind.DASHBOARD,
    "private.usercontent.example": HostKind.PRIVATE_CONTENT,
    "public.usercontent.example": HostKind.PUBLIC_CONTENT,
}

#: Local-dev host strings, mapped to their security class. These carry their dev
#: ports and are supplied ONLY by local config; they must never be deployed to
#: production. The two mappings are swappable and never co-deployed.
LOCAL_HOST_KINDS: dict[str, HostKind] = {
    "share.localhost:5174": HostKind.DASHBOARD,
    "private.localhost:5175": HostKind.PRIVATE_CONTENT,
    "public.localhost:5176": HostKind.PUBLIC_CONTENT,
}

#: Security-safe default for bare ``classify_host()`` calls: the production
#: mapping only. The app always passes an explicit, settings-derived map to the
#: gate, so this default is never the production fallback — and crucially it
#: never leaks the local dev hosts into a production classification.
DEFAULT_HOST_KINDS: dict[str, HostKind] = PROD_HOST_KINDS


def classify_host(
    raw_host: str | None,
    host_kinds: dict[str, HostKind] | None = None,
) -> HostKind:
    """Classify a raw ``Host`` header value to a :class:`HostKind`.

    Matching is exact (case-insensitive) against the registry keys, including
    the dev port for local hosts. Anything unrecognised — including a missing
    header — is :attr:`HostKind.UNKNOWN`.
    """

    if raw_host is None:
        return HostKind.UNKNOWN
    mapping = host_kinds if host_kinds is not None else DEFAULT_HOST_KINDS
    return mapping.get(raw_host.strip().lower(), HostKind.UNKNOWN)
