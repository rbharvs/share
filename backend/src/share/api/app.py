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

from pathlib import Path

from fastapi import FastAPI, Request, Response
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
from share.static_site import BUNDLED_STATIC_DIR, StaticSite

from .routes import router

#: HTTP statuses produced by FastAPI routing that map to ``route_not_allowed``.
_ROUTE_STATUSES = frozenset({404, 405})


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _maybe_spa_fallback(request: Request) -> Response | None:
    """HTML5-history SPA fallback for unmatched dashboard GETs.

    Runs only after routing has found no concrete match (a real 404), so every
    registered route — the whole API surface, ``/assets/*``, ``/robots.txt``,
    ``/u/{sha}`` — takes precedence naturally; the SPA is the last resort, never
    a route that shadows API paths. Restricted to GET on the dashboard host
    (``host_kind`` set by the gate), and ``/api/*`` / ``/assets/*`` are excluded
    so an API typo or a missing built asset stays ``route_not_allowed`` rather
    than silently returning the shell. Other hosts never reach here: the gate
    rejects the public/unknown hosts and confines the private host to its three
    allowed paths before routing.
    """

    if request.method != "GET":
        return None
    if getattr(request.state, "host_kind", None) is not HostKind.DASHBOARD:
        return None
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/assets/"):
        return None
    site = getattr(request.app.state, "static_site", None)
    if site is None:
        return None
    root_file = site.root_file_response(path.lstrip("/"))
    return root_file if root_file is not None else site.index_response()


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
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        # An unmatched dashboard GET is HTML5-history SPA navigation: serve the
        # shell instead of an error, but only after every concrete route missed.
        if exc.status_code == 404:
            spa = _maybe_spa_fallback(request)
            if spa is not None:
                return spa
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
    static_dir: Path | None = None,
) -> FastAPI:
    """Build the ASGI app. The same instance backs TestClient, uvicorn, and the
    Mangum handler.

    ``static_dir`` points at the built dashboard SPA bundle; it defaults to the
    package-bundled location populated by the build. Tests inject a temp bundle
    here to exercise the real SPA/asset/fallback serving without a frontend build.
    """

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

    # The dashboard SPA bundle (built assets + history fallback). App-scoped so
    # tests can point it at a temp bundle; defaults to the package-bundled dir
    # the build copies ``frontend/dist`` into. Served only on the dashboard host
    # (the host gate blocks the content hosts before routing).
    app.state.static_site = StaticSite(static_dir or BUNDLED_STATIC_DIR)

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
