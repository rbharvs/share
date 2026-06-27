"""Dashboard SPA static serving + SPA fallback + host precedence (slice 09).

A temp "built" bundle is injected via ``create_app(static_dir=...)`` so the real
serving path is exercised without a frontend build. Covers: the SPA and its
assets and robots are served only on the dashboard host; API routes take
precedence over the history fallback; and the private/public hosts never serve
the dashboard SPA.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import DASHBOARD_HOST, PRIVATE_HOST, PUBLIC_HOST
from share.api import create_app
from share.config import Settings

INDEX_HTML = (
    "<!doctype html><html><head><title>share dashboard</title>"
    '<script type="module" src="/assets/index-abc123.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)
ASSET_JS = "console.log('built dashboard bundle');"


@pytest.fixture
def built_bundle(tmp_path):
    """A minimal Vite-shaped built bundle (index + hashed asset + root file)."""

    (tmp_path / "index.html").write_text(INDEX_HTML)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_text(ASSET_JS)
    (tmp_path / "vite.svg").write_text("<svg/>")
    return tmp_path


@pytest.fixture
def client(built_bundle) -> TestClient:
    app = create_app(Settings(), static_dir=built_bundle)
    return TestClient(app, raise_server_exceptions=False)


# --- Dashboard host: SPA + assets + robots ---


def test_dashboard_root_serves_built_index(client):
    r = client.get("/", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "/assets/index-abc123.js" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_dashboard_serves_built_asset(client):
    r = client.get("/assets/index-abc123.js", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert r.text == ASSET_JS


def test_missing_built_asset_is_route_not_allowed(client):
    # Once built, a missing asset is a genuine miss, never the SPA shell.
    r = client.get("/assets/nope.js", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_dashboard_robots(client):
    r = client.get("/robots.txt", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "Disallow" in r.text


# --- SPA history fallback (dashboard only) ---


def test_unknown_browser_path_serves_spa_shell(client):
    # HTML5-history navigation to a client-side route returns index.html.
    r = client.get("/library/item/xyz", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "/assets/index-abc123.js" in r.text


def test_api_route_takes_precedence_over_spa_fallback(client):
    # An unknown /api path must stay route_not_allowed, not fall back to the SPA.
    r = client.get("/api/does-not-exist", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_root_level_vite_file_served_via_fallback(client):
    r = client.get("/vite.svg", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "svg" in r.text


def test_non_get_unknown_path_is_not_spa_fallback(client):
    r = client.post("/library", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


# --- Content hosts never serve the dashboard SPA ---


def test_private_host_root_is_not_the_spa(client):
    r = client.get("/", headers={"host": PRIVATE_HOST})
    assert r.status_code == 200
    assert "private content host" in r.text
    assert "/assets/index-abc123.js" not in r.text


def test_private_host_unknown_path_is_route_not_allowed(client):
    # The gate confines the private host; no SPA fallback can run there.
    r = client.get("/library", headers={"host": PRIVATE_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_private_host_assets_blocked(client):
    r = client.get("/assets/index-abc123.js", headers={"host": PRIVATE_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_public_host_never_serves_spa(client):
    r = client.get("/", headers={"host": PUBLIC_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"


def test_unknown_host_never_serves_spa(client):
    r = client.get("/library", headers={"host": "evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"


# --- Graceful degradation before any build exists ---


def test_unbuilt_bundle_serves_placeholder(tmp_path):
    # No index.html in the dir: dashboard still answers 200 with a placeholder.
    app = create_app(Settings(), static_dir=tmp_path / "empty")
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "dashboard" in r.text
