"""Host-gate middleware (the INNER middleware).

Runs the pure :func:`share.gate.evaluate` against the incoming host/path/method.
``BaseHTTPMiddleware``-raised :class:`ShareError`s are NOT caught by FastAPI's
exception handlers (the middleware sits outside the handler stack), so the gate
maps them to the structured envelope inline via the shared ``error_response``
primitive — the very same primitive the FastAPI handlers use.

On success it records the resolved ``HostKind`` on ``request.state.host_kind``
so route handlers can vary placeholder content per host without re-reading the
``Host`` header.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from share.errors import ShareError, error_response
from share.gate import evaluate
from share.hosts import HostKind


class HostGateMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        host_kinds: dict[str, HostKind] | None = None,
    ) -> None:
        super().__init__(app)
        self._host_kinds = host_kinds

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host")
        try:
            kind = evaluate(
                host,
                request.url.path,
                request.method,
                host_kinds=self._host_kinds,
            )
        except ShareError as exc:
            request_id = getattr(request.state, "request_id", None)
            return error_response(exc, request_id)

        request.state.host_kind = kind
        return await call_next(request)
