"""Exercise the same ASGI app through the Mangum handler with raw API Gateway
REST (v1) event dicts — proving TestClient and Lambda run identical code."""

from __future__ import annotations

import json

from share.handler import handler


def build_rest_event(method: str, path: str, host: str) -> dict:
    """A minimal API Gateway REST (v1) proxy event."""

    headers = {"Host": host}
    return {
        "resource": "/{proxy+}",
        "path": path,
        "httpMethod": method,
        "headers": headers,
        "multiValueHeaders": {k: [v] for k, v in headers.items()},
        "queryStringParameters": None,
        "multiValueQueryStringParameters": None,
        "pathParameters": {"proxy": path.lstrip("/")},
        "stageVariables": None,
        "requestContext": {
            "resourceId": "abc",
            "resourcePath": "/{proxy+}",
            "httpMethod": method,
            "path": f"/prod{path}",
            "stage": "prod",
            "identity": {"sourceIp": "203.0.113.1"},
            "requestId": "test-invoke-request",
        },
        "body": None,
        "isBase64Encoded": False,
    }


def invoke(method: str, path: str, host: str) -> dict:
    return handler(build_rest_event(method, path, host), None)


def test_dashboard_root_returns_200():
    resp = invoke("GET", "/", "share.example.com")
    assert resp["statusCode"] == 200
    assert "X-Request-Id" in resp["headers"] or "x-request-id" in resp["headers"]


def test_private_api_returns_403_route_not_allowed():
    resp = invoke("GET", "/api/health", "private.usercontent.example")
    assert resp["statusCode"] == 403
    body = json.loads(resp["body"])
    assert body["error"]["code"] == "route_not_allowed"


def test_public_host_returns_403():
    resp = invoke("GET", "/", "public.usercontent.example")
    assert resp["statusCode"] == 403
    assert json.loads(resp["body"])["error"]["code"] == "host_not_allowed"


def test_unknown_host_returns_403():
    resp = invoke("GET", "/", "evil.example.com")
    assert resp["statusCode"] == 403
    assert json.loads(resp["body"])["error"]["code"] == "host_not_allowed"
