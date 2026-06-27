"""Pure, string-only tests for the host registry and the host/path/method gate.

These exercise ``classify_host`` and ``gate.evaluate`` with zero FastAPI /
HTTP machinery — the gate is a pure decision function.
"""

from __future__ import annotations

import pytest

from share.errors import HostNotAllowedError, RouteNotAllowedError
from share.gate import evaluate
from share.hosts import LOCAL_HOST_KINDS, HostKind, classify_host


@pytest.mark.parametrize(
    "raw_host,expected",
    [
        ("share.example.com", HostKind.DASHBOARD),
        ("private.usercontent.example", HostKind.PRIVATE_CONTENT),
        ("public.usercontent.example", HostKind.PUBLIC_CONTENT),
        ("SHARE.EXAMPLE.COM", HostKind.DASHBOARD),  # case-insensitive
        ("evil.example.com", HostKind.UNKNOWN),
        ("", HostKind.UNKNOWN),
        (None, HostKind.UNKNOWN),
    ],
)
def test_classify_host_default_is_prod_only(raw_host, expected):
    """The default mapping is production-only; the dev hosts are NOT in it."""

    assert classify_host(raw_host) is expected


@pytest.mark.parametrize(
    "raw_host",
    ["share.localhost:5174", "private.localhost:5175", "public.localhost:5176"],
)
def test_default_mapping_excludes_dev_hosts(raw_host):
    """Dev hosts must never classify under the production default fallback."""

    assert classify_host(raw_host) is HostKind.UNKNOWN


@pytest.mark.parametrize(
    "raw_host,expected",
    [
        ("share.localhost:5174", HostKind.DASHBOARD),
        ("private.localhost:5175", HostKind.PRIVATE_CONTENT),
        ("public.localhost:5176", HostKind.PUBLIC_CONTENT),
        # Prod hosts are not co-deployed with the local mapping.
        ("share.example.com", HostKind.UNKNOWN),
    ],
)
def test_classify_host_with_local_mapping(raw_host, expected):
    assert classify_host(raw_host, LOCAL_HOST_KINDS) is expected


# --- Dashboard host: every path/method allowed at the gate level. ---


@pytest.mark.parametrize(
    "path,method",
    [
        ("/", "GET"),
        ("/assets/app.js", "GET"),
        ("/robots.txt", "GET"),
        ("/api/content", "GET"),
        ("/api/uploads/presign", "POST"),
        ("/anything/else", "GET"),
    ],
)
def test_dashboard_allows_everything(path, method):
    assert evaluate("share.example.com", path, method) is HostKind.DASHBOARD


@pytest.mark.parametrize(
    "path,method",
    [
        ("/u/abc123", "GET"),
        ("/u/abc123", "HEAD"),
        ("/u/abc123/", "GET"),
    ],
)
def test_dashboard_rejects_content_path(path, method):
    """The content-by-sha shape must never be served on the dashboard host."""

    with pytest.raises(RouteNotAllowedError):
        evaluate("share.example.com", path, method)


# --- Private content host: root/robots/content GET+HEAD only. ---


@pytest.mark.parametrize(
    "path,method",
    [
        ("/", "GET"),
        ("/", "HEAD"),
        ("/robots.txt", "GET"),
        ("/u/abc123", "GET"),
        ("/u/abc123", "HEAD"),
        ("/u/abc123/", "GET"),
    ],
)
def test_private_allows_root_robots_content_reads(path, method):
    assert (
        evaluate("private.usercontent.example", path, method) is HostKind.PRIVATE_CONTENT
    )


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/content", "GET"),  # dashboard API on private host
        ("/api/uploads/presign", "POST"),
        ("/u/abc123", "POST"),  # write to content
        ("/u/abc123", "DELETE"),
        ("/", "POST"),
        ("/robots.txt", "POST"),
    ],
)
def test_private_rejects_other_routes(path, method):
    with pytest.raises(RouteNotAllowedError):
        evaluate("private.usercontent.example", path, method)


# --- Public + unknown hosts: always host_not_allowed. ---


@pytest.mark.parametrize(
    "host",
    ["public.usercontent.example", "evil.example.com", "", None],
)
def test_public_and_unknown_hosts_rejected(host):
    with pytest.raises(HostNotAllowedError):
        evaluate(host, "/", "GET")
