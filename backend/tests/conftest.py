from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from share.api import create_app
from share.auth import (
    AccessConfig,
    AccessVerifier,
    LocalAccessSigner,
    StaticJwksProvider,
)
from share.hosts import HostKind

DASHBOARD_HOST = "share.example.com"
PRIVATE_HOST = "private.usercontent.example"
PUBLIC_HOST = "public.usercontent.example"

# Shared Access fixtures. The issuer/JWKS are shared across both private hosts;
# only the audience differs per host, so a token minted for one host is rejected
# on the other.
ISSUER = "https://team.cloudflareaccess.test"
DASHBOARD_AUDIENCE = "dashboard-audience-0000"
PRIVATE_AUDIENCE = "private-audience-1111"
OWNER_EMAIL = "owner@example.com"
JWKS_URL = "https://team.cloudflareaccess.test/cdn-cgi/access/certs"


# A minimal Vite-shaped built bundle: a hashed-name asset (Vite never emits a
# bare ``app.js`` — the build produces ``index-<hash>.js``) plus an index.html
# that references it. Host/route tests must exercise the REAL asset-serving path,
# so we inject this deterministic bundle rather than depending on the gitignored
# package ``static`` dir, whose presence/absence flips between the unbuilt
# placeholder and the real (hash-named) bundle and would otherwise make the suite
# pass or fail depending on whether ``make build`` has run.
_BUILT_ASSET_NAME = "index-test123.js"
_BUILT_ASSET_JS = "console.log('built dashboard bundle');"
_BUILT_INDEX_HTML = (
    "<!doctype html><html><head><title>share dashboard</title>"
    f'<script type="module" src="/assets/{_BUILT_ASSET_NAME}"></script></head>'
    '<body><div id="root"></div></body></html>'
)


@pytest.fixture
def built_static_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A deterministic built dashboard SPA bundle injected via ``static_dir``.

    Lets host/route tests exercise real static serving independent of whether the
    gitignored package ``static`` dir has been built. The asset name is hashed
    (Vite-shaped), so tests resolve it from ``index.html`` instead of guessing.
    """

    root = tmp_path_factory.mktemp("static")
    (root / "index.html").write_text(_BUILT_INDEX_HTML)
    assets = root / "assets"
    assets.mkdir()
    (assets / _BUILT_ASSET_NAME).write_text(_BUILT_ASSET_JS)
    return root


@pytest.fixture
def client(built_static_dir: Path) -> TestClient:
    # raise_server_exceptions=False so handler-mapped errors are observed as
    # real HTTP responses rather than re-raised exceptions. The bundle is injected
    # so the dashboard SPA/asset surface is served from a known built state.
    return TestClient(
        create_app(static_dir=built_static_dir), raise_server_exceptions=False
    )


@pytest.fixture
def signer() -> LocalAccessSigner:
    """A local signer standing in for the Cloudflare Access signing key."""

    return LocalAccessSigner(
        issuer=ISSUER, audience=DASHBOARD_AUDIENCE, allowed_email=OWNER_EMAIL
    )


@pytest.fixture
def access_config_map() -> dict[HostKind, AccessConfig]:
    """Per-host configs sharing one issuer/JWKS but distinct audiences."""

    return {
        HostKind.DASHBOARD: AccessConfig(
            issuer=ISSUER,
            audience=DASHBOARD_AUDIENCE,
            jwks_url=JWKS_URL,
            allowed_email=OWNER_EMAIL,
        ),
        HostKind.PRIVATE_CONTENT: AccessConfig(
            issuer=ISSUER,
            audience=PRIVATE_AUDIENCE,
            jwks_url=JWKS_URL,
            allowed_email=OWNER_EMAIL,
        ),
    }


@pytest.fixture
def verifier(
    signer: LocalAccessSigner,
    access_config_map: dict[HostKind, AccessConfig],
) -> AccessVerifier:
    """A verifier whose JWKS is backed by the signer (no network)."""

    return AccessVerifier(
        access_config_map, StaticJwksProvider(signer.jwks()), leeway=10
    )
