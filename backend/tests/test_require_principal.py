"""The ``require_principal`` FastAPI dependency and the 1:1 mapping of auth
errors onto the slice-01 structured error envelope.

The dependency is mounted on a real route reached through ``create_app`` so the
full stack runs: host gate -> route -> dependency -> verifier -> central
exception handler -> envelope. The app's verifier is replaced with a
``StaticJwksProvider``-backed one (the DI seam), so no network is touched.
"""

from __future__ import annotations

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from conftest import DASHBOARD_AUDIENCE, PRIVATE_AUDIENCE
from share.api import create_app
from share.auth import ACCESS_HEADER, Principal, require_principal
from share.config import Settings
from share.errors import (
    AuthInvalidError,
    AuthRequiredError,
    HostNotAllowedError,
    error_response,
)
from share.hosts import HostKind

LOCAL_DASHBOARD_HOST = "share.localhost:5174"

_dashboard_principal = require_principal(HostKind.DASHBOARD)


@pytest.fixture
def auth_client(verifier) -> TestClient:
    app = create_app(Settings.for_local())
    # Replace the network-backed verifier with the static test one (DI seam).
    app.state.access_verifier = verifier

    async def whoami(principal: Principal = Depends(_dashboard_principal)):
        return {"email": principal.email, "host": principal.host.value}

    app.add_api_route("/api/whoami", whoami, methods=["GET"])
    return TestClient(app, raise_server_exceptions=False)


def test_valid_token_authenticates(auth_client, signer):
    token = signer.sign(audience=DASHBOARD_AUDIENCE)
    r = auth_client.get(
        "/api/whoami",
        headers={"host": LOCAL_DASHBOARD_HOST, ACCESS_HEADER: token},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "owner@example.com"
    assert r.headers["X-Request-Id"]


def test_missing_token_maps_to_auth_required(auth_client):
    r = auth_client.get("/api/whoami", headers={"host": LOCAL_DASHBOARD_HOST})
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "auth_required"
    assert body["request_id"]
    assert r.headers["X-Request-Id"]


def test_invalid_token_maps_to_auth_invalid(auth_client, signer):
    # Right key/issuer, wrong audience -> auth_invalid through the mapper.
    token = signer.sign(audience=PRIVATE_AUDIENCE)
    r = auth_client.get(
        "/api/whoami",
        headers={"host": LOCAL_DASHBOARD_HOST, ACCESS_HEADER: token},
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth_invalid"


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (AuthRequiredError(), 401, "auth_required"),
        (AuthInvalidError(), 401, "auth_invalid"),
        (HostNotAllowedError(), 403, "host_not_allowed"),
    ],
)
def test_auth_errors_map_one_to_one_through_error_mapper(exc, status, code):
    # AuthError.code / .status_code map 1:1 onto the slice-01 error envelope.
    response = error_response(exc, "req-123")
    assert response.status_code == status
    assert exc.status_code == status
    assert exc.code == code
