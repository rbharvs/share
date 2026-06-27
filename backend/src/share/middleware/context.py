"""Request-context middleware (the OUTERMOST middleware).

Assigns a ``request_id`` to every request, exposes it on ``request.state`` for
downstream code (including the inner gate, which needs it to build the error
envelope), stamps every response with ``X-Request-Id``, and emits exactly one
structured JSON log line per request.

Because this is the outermost middleware, gate-rejection ``403``s produced by
the inner :class:`HostGateMiddleware` still flow back through here and therefore
still carry ``X-Request-Id`` and a logged line.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from share.logging import log_request

REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id

        response = await call_next(request)

        response.headers[REQUEST_ID_HEADER] = request_id
        log_request(
            request_id=request_id,
            host=request.headers.get("host"),
            path=request.url.path,
            method=request.method,
            status=response.status_code,
        )
        return response
