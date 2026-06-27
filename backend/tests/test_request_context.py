"""Request-id headers, gate-403 context propagation, and structured logging."""

from __future__ import annotations

import json
import logging

from conftest import DASHBOARD_HOST, PRIVATE_HOST, PUBLIC_HOST
from share.logging import REQUEST_LOGGER_NAME


def test_every_response_carries_request_id(client):
    r = client.get("/", headers={"host": DASHBOARD_HOST})
    assert r.status_code == 200
    assert r.headers.get("x-request-id")


def test_gate_rejection_carries_request_id_header_and_body(client):
    r = client.get("/", headers={"host": PUBLIC_HOST})
    assert r.status_code == 403
    header_id = r.headers.get("x-request-id")
    assert header_id
    # RequestContext is outer, HostGate is inner: the 403 envelope's request_id
    # matches the X-Request-Id header.
    assert r.json()["error"]["request_id"] == header_id


def test_route_not_allowed_rejection_carries_request_id(client):
    r = client.get("/api/health", headers={"host": PRIVATE_HOST})
    assert r.status_code == 403
    assert r.headers.get("x-request-id")
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


def test_one_structured_json_log_line_per_request(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER_NAME):
        client.get("/api/health", headers={"host": DASHBOARD_HOST})

    lines = [r.getMessage() for r in caplog.records if r.name == REQUEST_LOGGER_NAME]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["request_id"]
    assert payload["host"] == DASHBOARD_HOST
    assert payload["path"] == "/api/health"
    assert payload["method"] == "GET"
    assert payload["status"] == 200


def test_gate_rejection_is_logged_once(client, caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER_NAME):
        client.get("/", headers={"host": PUBLIC_HOST})

    lines = [r for r in caplog.records if r.name == REQUEST_LOGGER_NAME]
    assert len(lines) == 1
    payload = json.loads(lines[0].getMessage())
    assert payload["status"] == 403
    assert payload["host"] == PUBLIC_HOST
