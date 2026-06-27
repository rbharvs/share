"""FastAPI application factory.

Wires the request spine together:

- Routes (placeholder for slice 01).
- Centralised exception handlers that all funnel through the single
  ``error_response`` primitive, so the API boundary and the gate middleware
  emit byte-identical envelopes.
- Middleware stack with load-bearing order: ``RequestContextMiddleware`` is
  OUTERMOST (added last) so even gate-rejection ``403``s carry ``request_id`` +
  ``X-Request-Id``; ``HostGateMiddleware`` is inner (added first).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from share.auth import AccessVerifier, access_configs, caching_jwks_provider
from share.config import Settings, get_settings
from share.errors import (
    RouteNotAllowedError,
    ShareError,
    ValidationError,
    error_response,
)
from share.hosts import HostKind
from share.middleware import HostGateMiddleware, RequestContextMiddleware

from .routes import router

#: HTTP statuses produced by FastAPI routing that map to ``route_not_allowed``.
_ROUTE_STATUSES = frozenset({404, 405})


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ShareError)
    async def _share_error(request: Request, exc: ShareError) -> JSONResponse:
        return error_response(exc, _request_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(ValidationError(), _request_id(request))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Unknown paths (404) and unsupported methods (405) — including the
        # deliberately-absent DELETE — surface as the same stable code.
        if exc.status_code in _ROUTE_STATUSES:
            return error_response(RouteNotAllowedError(), _request_id(request))
        mapped = ShareError(str(exc.detail))
        mapped.status_code = exc.status_code
        return error_response(mapped, _request_id(request))


def create_app(
    settings: Settings | None = None,
    *,
    host_kinds: dict[str, HostKind] | None = None,
) -> FastAPI:
    """Build the ASGI app. The same instance backs TestClient, uvicorn, and the
    Mangum handler."""

    settings = settings or get_settings()

    # The gate's host map is derived from config: a single config swap (prod vs.
    # local Settings) re-points every host boundary. Falling back to the bundled
    # DEFAULT_HOST_KINDS is avoided here precisely so the production Lambda never
    # classifies the local dev hosts.
    if host_kinds is None:
        host_kinds = settings.host_kinds()

    app = FastAPI(
        title="share",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

    # The Access verifier is app-scoped but shares the module-level JWKS cache so
    # one fetch per cold start is reused across warm invocations. Routes reach it
    # through the `require_principal` dependency (slice 02); tests override it.
    app.state.access_verifier = AccessVerifier(
        access_configs(settings), caching_jwks_provider
    )

    app.include_router(router)
    _install_exception_handlers(app)

    # Inner first, outer last (Starlette runs last-added outermost).
    app.add_middleware(HostGateMiddleware, host_kinds=host_kinds)
    app.add_middleware(RequestContextMiddleware)

    return app
