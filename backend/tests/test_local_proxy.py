"""The local Access reverse proxy (slice 09).

Proves the deferred slice-02 forwarding: the proxy mints a fresh, signed
``Cf-Access-Jwt-Assertion`` per request and forwards it, and that header is
verified by FastAPI through the *identical* slice-02 path. The proxy is mounted
directly in front of the real FastAPI ASGI app via ``httpx.ASGITransport`` (no
sockets), so the same request that is ``401`` direct becomes authenticated
purely by the injected header. There is no auth bypass — only a local signer.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from share.api import create_app
from share.auth import (
    ACCESS_HEADER,
    AccessVerifier,
    LocalAccessSigner,
    StaticJwksProvider,
    access_configs,
)
from share.content import ContentItem, ContentStatus, SourceType
from share.devproxy import create_forwarding_app, local_dev_settings
from share.devproxy.config import (
    DASHBOARD_HOST,
    JWKS_PATH,
    LOCAL_DASHBOARD_AUDIENCE,
    LOCAL_ISSUER,
    LOCAL_PRIVATE_AUDIENCE,
    PRIVATE_HOST,
)
from share.errors import AuthInvalidError
from share.hosts import HostKind
from share.repository.metadata import ContentPage
from share.upload import get_repo


class _FakeRepo:
    """Minimal repo seam: the listing route only calls ``list_content``."""

    def __init__(self, items: list[ContentItem]) -> None:
        self._items = items

    def list_content(self, *, limit: int, start_key=None) -> ContentPage:
        return ContentPage(items=self._items[:limit], last_evaluated_key=None)


def _item(sha: str) -> ContentItem:
    return ContentItem(
        sha256=sha,
        source_type=SourceType.HTML,
        original_filename="demo.html",
        size_bytes=42,
        status=ContentStatus.UPLOADED,
        created_at="2026-06-24T17:52:00.000Z",
        updated_at="2026-06-24T17:52:00.000Z",
        published_at=None,
        created_by="owner@example.com",
        raw_key=f"raw/{sha}/source.html",
        private_artifact_key=f"artifacts/{sha}/index.html",
        public_key=None,
        last_upload_id="u-1",
    )


@pytest.fixture
def signer() -> LocalAccessSigner:
    # One signer/key for both audiences, mirroring the running proxy.
    settings = local_dev_settings()
    return LocalAccessSigner(
        issuer=LOCAL_ISSUER,
        audience=LOCAL_DASHBOARD_AUDIENCE,
        allowed_email=settings.allowed_owner_email,
    )


@pytest.fixture
def fastapi_app(signer: LocalAccessSigner):
    settings = local_dev_settings()
    app = create_app(settings)
    # The real slice-02 verifier, but its JWKS is the signer's (no network).
    app.state.access_verifier = AccessVerifier(
        access_configs(settings),
        StaticJwksProvider(signer.jwks()),
        leeway=10,
    )
    app.dependency_overrides[get_repo] = lambda: _FakeRepo(
        [_item(f"{n:064x}") for n in (3, 2, 1)]
    )
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def asgi_client(fastapi_app) -> httpx.AsyncClient:
    # Bind the proxy's httpx client straight to the FastAPI app — Host set by
    # base_url so the gate classifies it as the dashboard origin.
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url=f"http://{DASHBOARD_HOST}",
    )


def test_proxy_injected_token_authenticates_real_api(signer, asgi_client):
    proxy = create_forwarding_app(
        signer=signer,
        audience=LOCAL_DASHBOARD_AUDIENCE,
        forward_host=DASHBOARD_HOST,
        client=asgi_client,
    )
    client = TestClient(proxy, raise_server_exceptions=False)

    # No client-supplied credentials at all — the proxy injects the token.
    response = client.get("/api/content")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["sha256"] for item in body["items"]] == [
        f"{n:064x}" for n in (3, 2, 1)
    ]

    # Query strings (the opaque cursor, limit) survive the proxy hop verbatim.
    paged = client.get("/api/content?limit=2")
    assert paged.status_code == 200, paged.text
    assert len(paged.json()["items"]) == 2


def test_same_request_is_401_without_the_proxy(fastapi_app):
    # The identical request straight to FastAPI (no injected header) is rejected,
    # proving it is the proxy's signed assertion that authenticates.
    direct = TestClient(fastapi_app, raise_server_exceptions=False)
    response = direct.get("/api/content", headers={"host": DASHBOARD_HOST})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_proxy_serves_signer_jwks(signer, asgi_client):
    proxy = create_forwarding_app(
        signer=signer,
        audience=LOCAL_DASHBOARD_AUDIENCE,
        forward_host=DASHBOARD_HOST,
        client=asgi_client,
    )
    client = TestClient(proxy)
    # The verifier fetches this exact document to validate proxy-minted tokens.
    assert client.get(JWKS_PATH).json() == signer.jwks()


def test_proxy_mints_per_host_audience_verified_by_slice02_path(signer):
    # An echo upstream captures exactly what the proxy injects.
    captured: dict[str, str] = {}

    async def echo(request):
        captured["token"] = request.headers.get(ACCESS_HEADER, "")
        captured["host"] = request.headers.get("host", "")
        return JSONResponse({"ok": True})

    echo_app = Starlette(routes=[Route("/{p:path}", echo)])
    echo_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=echo_app), base_url="http://upstream"
    )
    private_proxy = create_forwarding_app(
        signer=signer,
        audience=LOCAL_PRIVATE_AUDIENCE,
        forward_host=PRIVATE_HOST,
        client=echo_client,
    )
    TestClient(private_proxy).get("/u/abc")

    assert captured["host"] == PRIVATE_HOST  # upstream sees the private origin

    settings = local_dev_settings()
    verifier = AccessVerifier(
        access_configs(settings), StaticJwksProvider(signer.jwks()), leeway=10
    )
    token = captured["token"]
    # Verified through the identical slice-02 path for the private host...
    principal = verifier.verify(token, HostKind.PRIVATE_CONTENT)
    assert principal.email == settings.allowed_owner_email
    # ...and the per-host audience is real: the private token is NOT a dashboard
    # token (audience mismatch fails closed).
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)
