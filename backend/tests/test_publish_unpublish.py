"""End-to-end tests for ``POST /api/content/{sha}/publish`` + ``/unpublish``.

The full dashboard spine runs: host gate -> CSRF/Origin guard -> Access auth ->
publish service -> S3 raw read + public put/delete + DynamoDB two-item content
transaction + the recording CDN invalidator fake. moto backs S3/DynamoDB; the
network-backed Access verifier is swapped for the conftest static one. Items are
seeded by driving the real presign+finalize flow over HTTP, then publish and
unpublish are driven over HTTP too.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from conftest import DASHBOARD_AUDIENCE
from share.api import create_app
from share.config import Settings
from share.publish import RecordingInvalidator, get_invalidator
from share.repository import DynamoMetadataRepository
from share.storage import S3ObjectStorage
from share.upload import get_repo, get_storage

LOCAL_DASHBOARD_HOST = "share.localhost:5174"
LOCAL_DASHBOARD_ORIGIN = "http://share.localhost:5174"
PRIVATE_HOST = "private.localhost:5175"
OWNER_EMAIL = "owner@example.com"
PRIVATE_BUCKET = "share-private"
PUBLIC_BUCKET = "share-public"
TABLE_NAME = "share"

# The public host the app under test (Settings.for_local) builds URLs from.
CONTENT_PUBLIC_HOST = "public.localhost:5176"

HTML_BYTES = b"<!doctype html><title>hi</title><script>alert(1)</script>"
MARKDOWN_BYTES = b"# Title\n\nHello <b>raw</b> world.\n"


@pytest.fixture
def aws_backends(_moto_aws):
    """Adapters over the session-scoped moto private+public S3 + DynamoDB table."""

    storage = S3ObjectStorage(
        client=_moto_aws.s3_client,
        private_bucket=PRIVATE_BUCKET,
        public_bucket=PUBLIC_BUCKET,
    )
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
def invalidator() -> RecordingInvalidator:
    return RecordingInvalidator()


@pytest.fixture
def publish_app(aws_backends, invalidator, verifier):
    """Dashboard app with verifier + storage/repo/invalidator seams overridden."""

    app = create_app(Settings.for_local())
    app.state.access_verifier = verifier
    app.dependency_overrides[get_storage] = lambda: aws_backends["storage"]
    app.dependency_overrides[get_repo] = lambda: aws_backends["repo"]
    app.dependency_overrides[get_invalidator] = lambda: invalidator
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(publish_app) -> TestClient:
    return TestClient(publish_app, raise_server_exceptions=False)


def _headers(
    signer,
    *,
    csrf: bool = True,
    origin: str | None = LOCAL_DASHBOARD_ORIGIN,
    host: str = LOCAL_DASHBOARD_HOST,
    token: str | None = "__default__",
):
    headers = {"host": host}
    if token == "__default__":
        token = signer.sign(audience=DASHBOARD_AUDIENCE)
    if token is not None:
        headers["Cf-Access-Jwt-Assertion"] = token
    if csrf:
        headers["X-Share-CSRF"] = "1"
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _seed(client, signer, aws, *, data: bytes, **body) -> str:
    """Drive presign+finalize over HTTP and return the SHA of a fresh item."""

    presigned = client.post(
        "/api/uploads/presign", headers=_headers(signer), json=body
    ).json()
    aws["s3"].put_object(
        Bucket=PRIVATE_BUCKET, Key=presigned["fields"]["key"], Body=data
    )
    finalized = client.post(
        "/api/uploads/finalize",
        headers=_headers(signer),
        json={"upload_id": presigned["upload_id"]},
    )
    assert finalized.status_code == 200, finalized.text
    return finalized.json()["sha256"]


def _publish(client, signer, sha, **header_kw):
    return client.post(
        f"/api/content/{sha}/publish", headers=_headers(signer, **header_kw)
    )


def _unpublish(client, signer, sha, **header_kw):
    return client.post(
        f"/api/content/{sha}/unpublish", headers=_headers(signer, **header_kw)
    )


def _public_object(aws, key: str) -> bytes | None:
    try:
        return aws["s3"].get_object(Bucket=PUBLIC_BUCKET, Key=key)["Body"].read()
    except ClientError:
        return None


def _list_item(aws, sha: str) -> dict:
    items = (
        aws["ddb"]
        .Table(TABLE_NAME)
        .query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(
                "USER#default"
            )
        )["Items"]
    )
    return next(i for i in items if i["sha256"] == sha)


# --------------------------------------------------------------------------- #
# Publish
# --------------------------------------------------------------------------- #


def test_publish_from_uploaded_creates_object_and_updates_both_items(
    client, aws_backends, signer
):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")

    response = _publish(client, signer, sha)
    assert response.status_code == 200, response.text
    body = response.json()

    # Common content-item response, now in the published shape.
    assert body["sha256"] == sha
    assert body["short_sha"] == sha[:12]
    assert body["status"] == "published"
    assert body["published_at"] is not None
    assert body["public_url"] == f"https://{CONTENT_PUBLIC_HOST}/u/{sha}"

    # Public object written at u/{sha}/index.html.
    public_key = f"u/{sha}/index.html"
    assert _public_object(aws_backends, public_key) == HTML_BYTES

    # BOTH metadata items reflect published, atomically (no drift).
    item = aws_backends["repo"].get_content_item(sha)
    assert item.status.value == "published"
    assert item.public_key == public_key
    assert item.published_at is not None

    listing = _list_item(aws_backends, sha)
    assert listing["status"] == "published"
    assert listing["public_key"] == public_key
    assert listing["published_at"] == item.published_at
    # List sort key still reuses the immutable created_at.
    assert listing["sk"] == f"CONTENT#{item.created_at}#{sha}"


def test_publish_regenerates_from_raw_not_copied_from_private_preview(
    client, aws_backends, signer
):
    sha = _seed(client, signer, aws_backends, data=MARKDOWN_BYTES, filename="notes.md")

    # Corrupt the PRIVATE preview artifact. If publish copied from it, the public
    # object would be corrupted too; instead publish must re-render from raw.
    aws_backends["s3"].put_object(
        Bucket=PRIVATE_BUCKET, Key=f"artifacts/{sha}/index.html", Body=b"CORRUPT"
    )

    response = _publish(client, signer, sha)
    assert response.status_code == 200, response.text

    public = _public_object(aws_backends, f"u/{sha}/index.html")
    assert public is not None
    assert public != b"CORRUPT"
    # A fresh render of the canonical raw markdown source.
    assert public.startswith(b"<!doctype html>")
    assert b"<title>notes.md</title>" in public
    assert b"<h1>Title</h1>" in public
    assert b"<b>raw</b>" in public


def test_republish_reuses_same_public_url_and_preserves_published_at(
    client, aws_backends, signer
):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")

    first = _publish(client, signer, sha).json()
    second = _publish(client, signer, sha).json()

    assert second["public_url"] == first["public_url"]
    assert second["status"] == "published"
    # Idempotent: published_at is preserved across republish.
    assert second["published_at"] == first["published_at"]
    assert _public_object(aws_backends, f"u/{sha}/index.html") == HTML_BYTES


def test_publish_repairs_missing_public_object(client, aws_backends, signer):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")
    _publish(client, signer, sha)

    # Metadata says published, but the public object is gone (drift/partial run).
    public_key = f"u/{sha}/index.html"
    aws_backends["s3"].delete_object(Bucket=PUBLIC_BUCKET, Key=public_key)
    assert _public_object(aws_backends, public_key) is None

    response = _publish(client, signer, sha)
    assert response.status_code == 200, response.text
    # Re-publish repaired the object.
    assert _public_object(aws_backends, public_key) == HTML_BYTES
    assert response.json()["status"] == "published"


def test_publish_reconciles_metadata_when_object_already_exists(
    client, aws_backends, signer
):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")

    # Public object exists but metadata is still 'uploaded' (drift). Publish must
    # reconcile the metadata to published.
    public_key = f"u/{sha}/index.html"
    aws_backends["s3"].put_object(Bucket=PUBLIC_BUCKET, Key=public_key, Body=HTML_BYTES)
    assert aws_backends["repo"].get_content_item(sha).status.value == "uploaded"

    response = _publish(client, signer, sha)
    assert response.status_code == 200, response.text
    assert aws_backends["repo"].get_content_item(sha).status.value == "published"
    assert _list_item(aws_backends, sha)["status"] == "published"


def test_publish_from_unpublished_round_trips(client, aws_backends, signer):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")
    first = _publish(client, signer, sha).json()
    _unpublish(client, signer, sha)

    again = _publish(client, signer, sha)
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["status"] == "published"
    # Same SHA-addressed public URL on republish.
    assert body["public_url"] == first["public_url"]
    assert _public_object(aws_backends, f"u/{sha}/index.html") == HTML_BYTES


def test_publish_unknown_sha_is_content_not_found(client, signer):
    response = _publish(client, signer, "deadbeef" * 8)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "content_not_found"


# --------------------------------------------------------------------------- #
# Unpublish
# --------------------------------------------------------------------------- #


def test_unpublish_deletes_object_marks_down_and_invalidates(
    client, aws_backends, signer, invalidator
):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")
    _publish(client, signer, sha)

    response = _unpublish(client, signer, sha)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "unpublished"
    assert body["public_url"] is None
    assert body["published_at"] is None

    # Public object deleted.
    assert _public_object(aws_backends, f"u/{sha}/index.html") is None

    # Both metadata items marked unpublished (no drift).
    item = aws_backends["repo"].get_content_item(sha)
    assert item.status.value == "unpublished"
    assert item.public_key is None
    assert _list_item(aws_backends, sha)["status"] == "unpublished"

    # The rewritten CloudFront cache key (/u/{sha}/index.html) is purged — the
    # URI the viewer-request rewrite caches under, exactly the deleted object's
    # path. Purging the bare /u/{sha} shapes would miss the real edge entry.
    assert invalidator.calls == [[f"/u/{sha}/index.html"]]


def test_unpublish_when_no_public_object_still_invalidates(
    client, aws_backends, signer, invalidator
):
    # Never published: unpublish is idempotent — deletes nothing, still marks
    # down and purges the rewritten cache key.
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")

    response = _unpublish(client, signer, sha)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unpublished"
    assert invalidator.calls == [[f"/u/{sha}/index.html"]]


def test_unpublish_unknown_sha_is_content_not_found(client, signer):
    response = _unpublish(client, signer, "deadbeef" * 8)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "content_not_found"


# --------------------------------------------------------------------------- #
# Boundary guards (CSRF / auth / host) hold for publish + unpublish too
# --------------------------------------------------------------------------- #


def test_publish_missing_csrf_rejected(client, aws_backends, signer):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")
    response = _publish(client, signer, sha, csrf=False)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_publish_bad_origin_rejected(client, aws_backends, signer):
    sha = _seed(client, signer, aws_backends, data=HTML_BYTES, filename="demo.html")
    response = _publish(client, signer, sha, origin="https://evil.example")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unauthenticated_publish_rejected(client):
    response = client.post(
        f"/api/content/{'a' * 64}/publish",
        headers={
            "host": LOCAL_DASHBOARD_HOST,
            "Origin": LOCAL_DASHBOARD_ORIGIN,
            "X-Share-CSRF": "1",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_publish_not_routable_on_private_host(client, signer):
    response = _publish(client, signer, "a" * 64, host=PRIVATE_HOST)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "route_not_allowed"


def test_no_delete_content_route_exists():
    # Story 23 by-absence: there is no content-delete route/state transition.
    app = create_app(Settings.for_local())
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        assert "DELETE" not in methods, f"unexpected DELETE on {route.path}"
