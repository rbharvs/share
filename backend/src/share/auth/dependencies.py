"""FastAPI adapters for the verifier.

``require_principal(host_kind)`` is a dependency factory: it reads the
``Cf-Access-Jwt-Assertion`` header off the request and runs the verifier for the
route's host kind, returning a :class:`Principal` or raising a slice-01 domain
error that the central exception handlers map to the structured envelope.

The verifier itself is resolved via :func:`get_access_verifier`, which reads the
instance the app factory stored on ``app.state`` — a DI seam tests override to
inject a :class:`StaticJwksProvider`-backed verifier without any network.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from share.hosts import HostKind

from .models import Principal
from .verifier import AccessVerifier

#: The header Cloudflare Access injects (and the local proxy mimics).
ACCESS_HEADER = "Cf-Access-Jwt-Assertion"


def get_access_verifier(request: Request) -> AccessVerifier:
    """Resolve the app-scoped verifier stored by the application factory."""

    return request.app.state.access_verifier


def require_principal(
    host_kind: HostKind,
) -> Callable[..., Principal]:
    """Build a dependency that authenticates the request for ``host_kind``."""

    def dependency(
        request: Request,
        verifier: AccessVerifier = Depends(get_access_verifier),
    ) -> Principal:
        token = request.headers.get(ACCESS_HEADER)
        return verifier.verify(token, host_kind)

    return dependency
