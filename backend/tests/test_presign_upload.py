"""End-to-end tests for ``POST /api/uploads/presign``.

The full dashboard spine runs: host gate -> CSRF/Origin guard -> Access auth ->
upload service -> S3 presign + DynamoDB session write. moto backs S3/DynamoDB;
the network-backed Access verifier is swapped for the conftest static one. moto
cannot serve the presigned multipart POST in-process, so we assert the returned
policy/fields and simulate the browser upload with ``put_object``.

DI seam: tests override ``get_storage``/``get_repo`` at the leaf (and clear them
afterward); the ``@lru_cache`` real providers are overridden, not invoked, so no
real boto3 client is constructed.
"""

from __future__ import annotations

import base64
import json
import time

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from conftest import DASHBOARD_AUDIENCE
from share.api import create_app
from share.config import Settings
from share.content import MAX_UPLOAD_BYTES
from share.repository import DynamoMetadataRepository
from share.storage import S3ObjectStorage
from share.upload import get_repo, get_storage

LOCAL_DASHBOARD_HOST = "share.localhost:5174"
LOCAL_DASHBOARD_ORIGIN = "http://share.localhost:5174"
PRIVATE_HOST = "private.localhost:5175"
OWNER_EMAIL = "owner@example.com"
PRIVATE_BUCKET = "share-private"
TABLE_NAME = "share"


@pytest.fixture
def aws_backends():
    """A moto-backed S3 bucket + DynamoDB table and the matching adapters."""

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=PRIVATE_BUCKET)

        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.Table(TABLE_NAME).wait_until_exists()

        storage = S3ObjectStorage(client=s3, private_bucket=PRIVATE_BUCKET)
        repo = DynamoMetadataRepository(
            table_name=TABLE_NAME,
            resource=ddb,
            client=boto3.client("dynamodb", region_name="us-east-1"),
        )
        yield {"s3": s3, "ddb": ddb, "storage": storage, "repo": repo}


@pytest.fixture
def presign_app(aws_backends, verifier):
    """The dashboard app with the verifier + storage/repo seams overridden."""

    app = create_app(Settings.for_local())
    app.state.access_verifier = verifier
    app.dependency_overrides[get_storage] = lambda: aws_backends["storage"]
    app.dependency_overrides[get_repo] = lambda: aws_backends["repo"]
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(presign_app) -> TestClient:
    return TestClient(presign_app, raise_server_exceptions=False)


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


def _decode_policy(fields: dict[str, str]) -> dict:
    return json.loads(base64.b64decode(fields["policy"]))


def test_presign_creates_session_and_returns_size_policy(client, aws_backends, signer):
    before = int(time.time())
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer),
        json={"filename": "demo.html", "content_type": "text/html"},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    upload_id = body["upload_id"]
    assert upload_id
    assert body["max_size_bytes"] == MAX_UPLOAD_BYTES == 5242880
    assert body["fields"]["key"] == f"tmp/{upload_id}"
    assert body["fields"]["key"].startswith("tmp/")
    assert body["url"]

    # The 5 MB cap is carried in the presigned POST policy (first size gate).
    conditions = _decode_policy(body["fields"])["conditions"]
    assert ["content-length-range", 0, MAX_UPLOAD_BYTES] in conditions

    # Session item persisted with TTL + the verified principal as created_by.
    session = aws_backends["repo"].get_upload_session(upload_id)
    assert session is not None
    assert session.created_by == OWNER_EMAIL
    assert session.original_filename == "demo.html"
    assert session.source_type.value == "html"
    assert session.tmp_key == f"tmp/{upload_id}"
    assert session.max_size_bytes == MAX_UPLOAD_BYTES
    assert before + 3600 <= session.expires_at_epoch <= int(time.time()) + 3600


def test_presign_infers_markdown_source_type(client, aws_backends, signer):
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer),
        json={"filename": "notes.md"},
    )
    assert response.status_code == 200, response.text
    session = aws_backends["repo"].get_upload_session(response.json()["upload_id"])
    assert session.source_type.value == "markdown"


def test_explicit_source_type_override_wins(client, aws_backends, signer):
    # .html extension, but the owner explicitly declares markdown.
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer),
        json={"filename": "page.html", "source_type": "markdown"},
    )
    assert response.status_code == 200, response.text
    session = aws_backends["repo"].get_upload_session(response.json()["upload_id"])
    assert session.source_type.value == "markdown"


def test_presigned_key_round_trips_via_browser_put(client, aws_backends, signer):
    # moto cannot serve the multipart POST; simulate the browser upload directly
    # at the pinned key and confirm the storage adapter reads it back.
    body = client.post(
        "/api/uploads/presign",
        headers=_headers(signer),
        json={"filename": "demo.html"},
    ).json()
    key = body["fields"]["key"]
    aws_backends["s3"].put_object(Bucket=PRIVATE_BUCKET, Key=key, Body=b"<h1>hi</h1>")
    assert aws_backends["storage"].get_object(key) == b"<h1>hi</h1>"
    assert aws_backends["storage"].get_object("tmp/missing") is None


def test_unsupported_source_type_rejected(client, signer):
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer),
        json={"filename": "mystery.bin"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_source_type"


def test_missing_csrf_header_rejected(client, signer):
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer, csrf=False),
        json={"filename": "demo.html"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_cross_origin_rejected(client, signer):
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer, origin="https://evil.example"),
        json={"filename": "demo.html"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_missing_origin_rejected(client, signer):
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer, origin=None),
        json={"filename": "demo.html"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_no_cors_headers_emitted(client, signer):
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer),
        json={"filename": "demo.html"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_unauthenticated_presign_rejected(client):
    # Valid CSRF + Origin, but no Access JWT.
    response = client.post(
        "/api/uploads/presign",
        headers={
            "host": LOCAL_DASHBOARD_HOST,
            "Origin": LOCAL_DASHBOARD_ORIGIN,
            "X-Share-CSRF": "1",
        },
        json={"filename": "demo.html"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_presign_not_routable_on_private_host(client, signer):
    # Dashboard mutation APIs must never be exposed on the private content host.
    response = client.post(
        "/api/uploads/presign",
        headers=_headers(signer, host=PRIVATE_HOST),
        json={"filename": "demo.html"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "route_not_allowed"


def test_leaf_providers_overridden_not_invoked(presign_app):
    # The DI contract: the real lru_cache S3/Dynamo providers are overridden by
    # the moto-backed seams, so they are never invoked under test.
    assert get_storage in presign_app.dependency_overrides
    assert get_repo in presign_app.dependency_overrides
