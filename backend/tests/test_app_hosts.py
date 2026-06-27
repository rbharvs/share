"""Route-level tests per host class via TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import DASHBOARD_HOST, PRIVATE_HOST, PUBLIC_HOST
from share.api import create_app
from share.config import Settings

# --- Dashboard host ---


def test_dashboard_root_ok(client):
    r = client.get("/", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "dashboard" in r.text


def test_dashboard_api_ok(client):
    r = client.get("/api/health", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard_assets_ok(client):
    r = client.get("/assets/app.js", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200


def test_dashboard_robots_ok(client):
    r = client.get("/robots.txt", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert "Disallow" in r.text


def test_dashboard_rejects_content_path(client):
    # /u/{sha} is a registered route, but uploaded content must never be served
    # same-origin as the dashboard; the gate rejects it before routing.
    r = client.get("/u/abc123", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


# --- Private content host ---


def test_private_root_ok(client):
    r = client.get("/", headers={"host": PRIVATE_HOST})
    assert r.status_code == 200
    assert "private content host" in r.text


def test_private_content_get_ok(client):
    r = client.get("/u/abc123", headers={"host": PRIVATE_HOST})
    assert r.status_code == 200


def test_private_content_head_ok(client):
    r = client.head("/u/abc123", headers={"host": PRIVATE_HOST})
    assert r.status_code == 200
    assert r.content == b""


def test_private_robots_ok(client):
    r = client.get("/robots.txt", headers={"host": PRIVATE_HOST})
    assert r.status_code == 200


def test_private_rejects_dashboard_api(client):
    r = client.get("/api/health", headers={"host": PRIVATE_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_private_rejects_post_to_content(client):
    r = client.post("/u/abc123", headers={"host": PRIVATE_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


# --- Public + unknown hosts ---


def test_public_host_forbidden(client):
    r = client.get("/", headers={"host": PUBLIC_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"


def test_unknown_host_forbidden(client):
    r = client.get("/", headers={"host": "evil.example.com"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"


# --- Config-driven host boundary (no hardcoded dev-host fallback) ---


def test_prod_app_does_not_classify_dev_host_as_dashboard():
    # A production-config app (default Settings) must NOT honor the local dev
    # hosts; spoofing Host: share.localhost:5174 at the origin is host_not_allowed.
    app = TestClient(create_app(Settings()), raise_server_exceptions=False)
    r = app.get("/", headers={"host": "share.localhost:5174"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"

    r = app.get("/u/abc", headers={"host": "private.localhost:5175"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"


def test_local_config_repoints_host_boundaries():
    # Swapping the injected config re-points every host boundary through
    # create_app: the dev hosts now classify, and the prod hosts do not.
    app = TestClient(
        create_app(Settings.for_local()), raise_server_exceptions=False
    )

    r = app.get("/", headers={"host": "share.localhost:5174"})
    assert r.status_code == 200
    assert "dashboard" in r.text

    r = app.get("/u/abc", headers={"host": "private.localhost:5175"})
    assert r.status_code == 200

    # Prod hosts are not co-deployed with the local mapping.
    r = app.get("/", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"


def test_remapped_settings_change_classification():
    # Arbitrary remapped hosts flow through create_app -> gate.
    settings = Settings(
        dashboard_host="dash.example.test",
        private_host="priv.example.test",
        public_host="pub.example.test",
    )
    app = TestClient(create_app(settings), raise_server_exceptions=False)

    r = app.get("/", headers={"host": "dash.example.test"})
    assert r.status_code == 200
    assert "dashboard" in r.text

    r = app.get("/", headers={"host": "priv.example.test"})
    assert r.status_code == 200
    assert "private content host" in r.text

    # The old default dashboard host is no longer classified.
    r = app.get("/", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "host_not_allowed"
