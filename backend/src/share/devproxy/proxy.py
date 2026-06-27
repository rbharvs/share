"""The local Access reverse proxy that slice 02 deferred.

A Starlette + httpx reverse proxy that mints a fresh, Cloudflare-shaped
``Cf-Access-Jwt-Assertion`` per request with :class:`LocalAccessSigner` and
forwards to an upstream, exactly mimicking what Cloudflare Access does in front
of the real hosts. The injected token is verified by FastAPI through the
*identical* slice-02 verification path (``AccessVerifier`` + ``CachingJwksProvider``
fetching this proxy's JWKS) — there is no auth bypass, only a local signing key.

One signer key backs both listeners, so a single JWKS document verifies both the
dashboard- and private-audience tokens. The signer's JWKS is served at
:data:`~share.devproxy.config.JWKS_PATH`, intercepted before forwarding so it is
answered by the proxy itself rather than passed through to the upstream.

The httpx client is injectable so tests can mount the proxy directly in front of
the FastAPI ASGI app (via ``httpx.ASGITransport``) and assert that an
otherwise-401 request becomes authenticated purely by the injected header.
"""

from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from share.auth import ACCESS_HEADER, LocalAccessSigner

from .config import JWKS_PATH

#: Per RFC 7230 these are connection-scoped and must not be forwarded; ``host``
#: and ``content-length`` are also dropped so httpx recomputes them correctly.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)

_FORWARDED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _strip_hop_by_hop(headers: object) -> dict[str, str]:
    return {
        k: v
        for k, v in headers.items()  # type: ignore[attr-defined]
        if k.lower() not in _HOP_BY_HOP
    }


def create_forwarding_app(
    *,
    signer: LocalAccessSigner,
    audience: str,
    upstream: str | None = None,
    forward_host: str,
    client: httpx.AsyncClient | None = None,
) -> Starlette:
    """Build a reverse-proxy app for one host role (dashboard or private).

    ``audience`` is the local audience minted into every forwarded request, so
    the dashboard listener mints dashboard-audience tokens and the private
    listener mints private-audience tokens. ``forward_host`` is the ``Host`` the
    upstream observes, so FastAPI classifies the request as the intended host
    even when reached through Vite's own ``/api`` proxy. ``client`` is injectable
    for tests; otherwise an httpx client bound to ``upstream`` is created.
    """

    if client is None:
        if upstream is None:  # pragma: no cover - misuse guard
            raise ValueError("either client or upstream must be provided")
        client = httpx.AsyncClient(base_url=upstream, timeout=30.0)

    async def serve_jwks(_request: Request) -> Response:
        # Answered by the proxy, never forwarded: this is the certs endpoint the
        # FastAPI verifier fetches to validate the tokens we mint.
        return JSONResponse(signer.jwks())

    async def forward(request: Request) -> Response:
        body = await request.body()
        headers = _strip_hop_by_hop(request.headers)
        headers["host"] = forward_host
        # A fresh token per request (fresh nonce/sub), exactly like Access.
        headers[ACCESS_HEADER] = signer.sign(audience=audience)

        # Preserve the raw query string verbatim (opaque cursors etc.) by
        # appending it to the path rather than re-encoding through params.
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        upstream_request = client.build_request(
            request.method,
            target,
            headers=headers,
            content=body,
        )
        upstream_response = await client.send(upstream_request)
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=_strip_hop_by_hop(upstream_response.headers),
        )

    return Starlette(
        routes=[
            Route(JWKS_PATH, serve_jwks, methods=["GET"]),
            Route("/{path:path}", forward, methods=_FORWARDED_METHODS),
        ]
    )
