"""By-absence guards (story 23): no DELETE; unknown routes -> route_not_allowed."""

from __future__ import annotations

from conftest import DASHBOARD_HOST
from share.api import create_app


def test_unknown_route_is_route_not_allowed(client):
    r = client.get("/api/does-not-exist", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_no_delete_route_exists():
    app = create_app()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        assert "DELETE" not in methods, f"unexpected DELETE on {route.path}"


def test_delete_request_is_route_not_allowed(client):
    # DELETE on the dashboard host: gate allows, routing rejects -> mapped code.
    r = client.request(
        "DELETE", "/api/content/abc123", headers={"host": DASHBOARD_HOST}
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"
