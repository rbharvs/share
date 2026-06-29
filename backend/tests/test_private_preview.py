"""End-to-end tests for ``GET``/``HEAD /u/{sha}`` on the private content host.

The full private spine runs: host gate -> private-audience Access auth -> preview
service -> DynamoDB metadata lookup + S3 artifact read. moto backs S3/DynamoDB;
the network-backed Access verifier is swapped for the conftest static one. Items
are seeded directly through the storage/repo seams (finalize is covered by its
own suite) so these tests stay focused on the read path, headers, and the host
boundary.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from conftest import DASHBOARD_AUDIENCE, PRIVATE_AUDIENCE
from share.api import create_app
from share.config import Settings
from share.content import (
    RENDERED_CONTENT_CSP,
    ContentItem,
    ContentStatus,
    SourceType,
)
from share.repository import DynamoMetadataRepository
from share.storage import S3ObjectStorage
from share.upload import get_repo, get_storage

PRIVATE_HOST = "private.localhost:5175"
DASHBOARD_HOST = "share.localhost:5174"
OWNER_EMAIL = "owner@example.com"
PRIVATE_BUCKET = "share-private"
TABLE_NAME = "share"

ARTIFACT = b"<!doctype html><title>hi</title><script>alert(1)</script>"
SHA = hashlib.sha256(b"some-canonical-raw-source").hexdigest()


@pytest.fixture
def aws_backends(_moto_aws):
    """Adapters over the session-scoped moto S3 bucket + DynamoDB table."""

    storage = S3ObjectStorage(client=_moto_aws.s3_client, private_bucket=PRIVATE_BUCKET)
    repo = DynamoMetadataRepository(
        table_name=TABLE_NAME,
        resource=_moto_aws.ddb_resource,
        client=_moto_aws.ddb_client,
    )
    return {
        "s3": _moto_aws.s3_client,
        "ddb": _moto_aws.ddb_resource,
        "storage": storage,
        "repo": repo,
    }


@pytest.fixture
def preview_app(aws_backends, verifier):
    """The app with the verifier + storage/repo seams overridden for moto."""

    app = create_app(Settings.for_local())
    app.state.access_verifier = verifier
    app.dependency_overrides[get_storage] = lambda: aws_backends["storage"]
    app.dependency_overrides[get_repo] = lambda: aws_backends["repo"]
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(preview_app) -> TestClient:
    return TestClient(preview_app, raise_server_exceptions=False)


def _seed(
    aws,
    *,
    sha: str = SHA,
    artifact: bytes = ARTIFACT,
    status: ContentStatus = ContentStatus.UPLOADED,
    source_type: SourceType = SourceType.HTML,
    filename: str = "demo.html",
) -> ContentItem:
    """Seed a finalized item: its artifact object + the two metadata items."""

    storage = aws["storage"]
    artifact_key = storage.artifact_key(sha)
    storage.put_object(artifact_key, artifact, content_type="text/html; charset=utf-8")
    published = status is ContentStatus.PUBLISHED
    item = ContentItem(
        sha256=sha,
        source_type=source_type,
        original_filename=filename,
        size_bytes=len(artifact),
        status=status,
        created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
        published_at="2026-01-02T00:00:00.000Z" if published else None,
        created_by=OWNER_EMAIL,
        raw_key=storage.raw_key(sha, source_type),
        private_artifact_key=artifact_key,
        public_key=f"public/{sha}" if published else None,
        last_upload_id="seed-upload",
    )
    aws["repo"].put_content_item(item)
    return item


def _private_token(signer) -> str:
    return signer.sign(audience=PRIVATE_AUDIENCE)


def _headers(signer, *, host: str = PRIVATE_HOST, token: str | None = "__private__"):
    headers = {"host": host}
    if token == "__private__":
        token = _private_token(signer)
    if token is not None:
        headers["Cf-Access-Jwt-Assertion"] = token
    return headers


# --------------------------------------------------------------------------- #
# Happy path: GET / HEAD
# --------------------------------------------------------------------------- #


def test_get_returns_artifact_with_sandbox_headers(client, aws_backends, signer):
    _seed(aws_backends)
    r = client.get(f"/u/{SHA}", headers=_headers(signer))

    assert r.status_code == 200, r.text
    assert r.content == ARTIFACT

    # The exact rendered-content header set (slice 07 spec). The CSP sandbox
    # WITHOUT allow-same-origin is the load-bearing isolation defense.
    assert r.headers["content-type"] == "text/html; charset=utf-8"
    assert r.headers["content-security-policy"] == RENDERED_CONTENT_CSP
    assert r.headers["content-security-policy"] == (
        "sandbox allow-scripts allow-forms allow-popups allow-downloads"
    )
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"


def test_head_returns_metadata_without_body(client, aws_backends, signer):
    _seed(aws_backends)
    r = client.head(f"/u/{SHA}", headers=_headers(signer))

    assert r.status_code == 200, r.text
    assert r.content == b""
    # Same security headers as GET ...
    assert r.headers["content-security-policy"] == RENDERED_CONTENT_CSP
    assert "allow-same-origin" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    # ... and Content-Length reflects the body GET would have returned.
    assert r.headers["content-length"] == str(len(ARTIFACT))


def test_published_item_is_served_on_private_host(client, aws_backends, signer):
    # The private host is authenticated, so it serves the owner's full library
    # regardless of publish status (not just the unpublished subset).
    _seed(aws_backends, status=ContentStatus.PUBLISHED)
    r = client.get(f"/u/{SHA}", headers=_headers(signer))
    assert r.status_code == 200
    assert r.content == ARTIFACT


# --------------------------------------------------------------------------- #
# Missing content
# --------------------------------------------------------------------------- #


def test_missing_sha_returns_content_not_found(client, signer):
    r = client.get(f"/u/{'0' * 64}", headers=_headers(signer))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "content_not_found"


def test_head_missing_sha_returns_content_not_found(client, signer):
    r = client.head(f"/u/{'0' * 64}", headers=_headers(signer))
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Auth: required + correct private audience
# --------------------------------------------------------------------------- #


def test_unauthenticated_get_rejected(client, aws_backends, signer):
    _seed(aws_backends)
    r = client.get(f"/u/{SHA}", headers=_headers(signer, token=None))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth_required"


def test_dashboard_audience_token_rejected_on_private_host(
    client, aws_backends, signer
):
    # A token minted for the DASHBOARD Access app must not unlock private
    # content: the private host requires the private audience.
    _seed(aws_backends)
    token = signer.sign(audience=DASHBOARD_AUDIENCE)
    r = client.get(f"/u/{SHA}", headers=_headers(signer, token=token))
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "auth_invalid"


# --------------------------------------------------------------------------- #
# Host boundary: only root/robots/content GET+HEAD reachable here
# --------------------------------------------------------------------------- #


def test_dashboard_api_on_private_host_is_route_not_allowed(client, signer):
    # A dashboard mutation/list API path on the private host is rejected by the
    # gate before any handler/auth — no dashboard APIs are reachable here.
    r = client.get("/api/content", headers=_headers(signer))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_post_to_content_on_private_host_is_route_not_allowed(client, signer):
    r = client.post(f"/u/{SHA}", headers=_headers(signer))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"


def test_content_path_on_dashboard_host_is_route_not_allowed(
    client, aws_backends, signer
):
    # Uploaded content must never be served same-origin as the dashboard.
    _seed(aws_backends)
    r = client.get(f"/u/{SHA}", headers=_headers(signer, host=DASHBOARD_HOST))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "route_not_allowed"
