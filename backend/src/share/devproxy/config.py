"""Local-dev Access constants and the local FastAPI settings.

These values exist ONLY for local development: a distinct issuer/audiences and a
JWKS URL that points back at the local reverse proxy. They are never deployed —
production config carries the real Cloudflare issuer/audiences instead, and the
gate/verifier code is byte-identical between the two. There is deliberately no
``APP_ENV`` auth bypass; only this injected config differs from production.
"""

from __future__ import annotations

from share.config import Settings

#: A local issuer string distinct from the Cloudflare one. A token minted with
#: this issuer is rejected by a production-configured app (different issuer).
LOCAL_ISSUER = "https://share-local.access.localdev"

#: Separate local audiences per host, mirroring Cloudflare's per-app audiences,
#: so a dashboard token is rejected on the private host and vice versa.
LOCAL_DASHBOARD_AUDIENCE = "share-local-dashboard"
LOCAL_PRIVATE_AUDIENCE = "share-local-private"

#: Ports the reverse proxy listens on (the browser-facing local origins).
DASHBOARD_PROXY_PORT = 5174
PRIVATE_PROXY_PORT = 5175

#: Where each proxy listener forwards by default. The dashboard proxy fronts the
#: Vite dev server (which itself proxies ``/api/*`` to FastAPI); the private
#: proxy fronts FastAPI directly. ``mise run preview`` overrides the dashboard
#: upstream to FastAPI so the built SPA is served production-shape.
VITE_DEV_URL = "http://127.0.0.1:5173"
FASTAPI_URL = "http://127.0.0.1:8000"

#: The Host header FastAPI must observe to classify each request (with dev port).
DASHBOARD_HOST = "share.localhost:5174"
PRIVATE_HOST = "private.localhost:5175"

#: The proxy serves its signer's JWKS here; FastAPI's verifier fetches it through
#: the same ``CachingJwksProvider`` path used for the real Cloudflare certs.
JWKS_PATH = "/cdn-cgi/access/certs"
JWKS_URL = f"http://127.0.0.1:{DASHBOARD_PROXY_PORT}{JWKS_PATH}"


def local_dev_settings(**overrides: object) -> Settings:
    """Local FastAPI settings: dev hosts plus the local Access config.

    Wires the verifier to the local issuer/audiences and the proxy's JWKS URL so
    a proxy-minted token verifies through the identical slice-02 path.
    """

    base: dict[str, object] = {
        "access_issuer": LOCAL_ISSUER,
        "dashboard_audience": LOCAL_DASHBOARD_AUDIENCE,
        "private_audience": LOCAL_PRIVATE_AUDIENCE,
        "jwks_url": JWKS_URL,
    }
    base.update(overrides)
    return Settings.for_local(**base)
