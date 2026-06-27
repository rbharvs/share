"""End-to-end tests for ``POST /api/uploads/finalize``.

The full dashboard spine runs: host gate -> CSRF/Origin guard -> Access auth ->
upload service -> S3 head/get/put/delete + DynamoDB session read + two-item
content transaction. moto backs S3/DynamoDB; the network-backed Access verifier
is swapped for the conftest static one. The "browser upload" to the presigned
key is simulated with ``put_object`` (moto cannot serve the multipart POST), then
finalize is driven over real HTTP.
"""

from __future__ import annotations

import hashlib
import time

import boto3
import pytest
from botocore.exceptions import ClientError
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

# The hosts the app under test (Settings.for_local) builds finalize URLs from.
CONTENT_PRIVATE_HOST = "private.localhost:5175"
CONTENT_PUBLIC_HOST = "public.localhost:5176"

HTML_BYTES = b"<!doctype html><title>hi</title><script>alert(1)</script>"
MARKDOWN_BYTES = b"# Title\n\nHello <b>raw</b> world.\n"


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
def finalize_app(aws_backends, verifier):
    """The dashboard app with the verifier + storage/repo seams overridden."""

    app = create_app(Settings.for_local())
    app.state.access_verifier = verifier
    app.dependency_overrides[get_storage] = lambda: aws_backends["storage"]
    app.dependency_overrides[get_repo] = lambda: aws_backends["repo"]
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(finalize_app) -> TestClient:
    return TestClient(finalize_app, raise_server_exceptions=False)


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


def _presign(client, signer, **body) -> dict:
    response = client.post("/api/uploads/presign", headers=_headers(signer), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _put_temp(aws, key: str, data: bytes) -> None:
    aws["s3"].put_object(Bucket=PRIVATE_BUCKET, Key=key, Body=data)


def _finalize(client, signer, upload_id: str, **header_kw):
    return client.post(
        "/api/uploads/finalize",
        headers=_headers(signer, **header_kw),
        json={"upload_id": upload_id},
    )


def _upload_and_finalize(client, signer, aws, *, data: bytes, **body):
    presigned = _presign(client, signer, **body)
    _put_temp(aws, presigned["fields"]["key"], data)
    return presigned["upload_id"], _finalize(client, signer, presigned["upload_id"])


def _object_exists(aws, key: str) -> bool:
    try:
        aws["s3"].head_object(Bucket=PRIVATE_BUCKET, Key=key)
        return True
    except ClientError:
        return False


def _list_items(aws) -> list[dict]:
    return (
        aws["ddb"]
        .Table(TABLE_NAME)
        .query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(
                "USER#default"
            )
        )["Items"]
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_finalize_html_creates_immutable_sha_addressed_item(
    client, aws_backends, signer
):
    upload_id, response = _upload_and_finalize(
        client, signer, aws_backends, data=HTML_BYTES, filename="demo.html"
    )

    assert response.status_code == 200, response.text
    body = response.json()

    sha = hashlib.sha256(HTML_BYTES).hexdigest()
    assert body["sha256"] == sha
    assert body["short_sha"] == sha[:12]
    assert body["source_type"] == "html"
    assert body["original_filename"] == "demo.html"
    assert body["size_bytes"] == len(HTML_BYTES)
    assert body["status"] == "uploaded"
    assert body["published_at"] is None
    assert body["public_url"] is None
    assert body["private_url"] == f"https://{CONTENT_PRIVATE_HOST}/u/{sha}"
    assert body["created_at"] == body["updated_at"]

    # Raw + artifact written; HTML artifact is byte-identical to the raw upload.
    raw_key = f"raw/{sha}/source.html"
    artifact_key = f"artifacts/{sha}/index.html"
    assert aws_backends["storage"].get_object(raw_key) == HTML_BYTES
    assert aws_backends["storage"].get_object(artifact_key) == HTML_BYTES

    # Temp object deleted LAST.
    assert aws_backends["storage"].get_object(f"tmp/{upload_id}") is None

    # Both metadata items present and consistent.
    item = aws_backends["repo"].get_content_item(sha)
    assert item is not None
    assert item.status.value == "uploaded"
    assert item.size_bytes == len(HTML_BYTES)
    assert isinstance(item.size_bytes, int)
    assert item.raw_key == raw_key
    assert item.private_artifact_key == artifact_key
    assert item.public_key is None
    assert item.created_by == OWNER_EMAIL
    assert item.last_upload_id == upload_id

    list_items = _list_items(aws_backends)
    assert len(list_items) == 1
    listing = list_items[0]
    assert listing["sk"] == f"CONTENT#{item.created_at}#{sha}"
    assert listing["sha256"] == sha
    assert int(listing["size_bytes"]) == len(HTML_BYTES)
    assert listing["status"] == "uploaded"


def test_finalize_markdown_renders_wrapped_artifact(client, aws_backends, signer):
    _, response = _upload_and_finalize(
        client, signer, aws_backends, data=MARKDOWN_BYTES, filename="notes.md"
    )
    assert response.status_code == 200, response.text
    sha = hashlib.sha256(MARKDOWN_BYTES).hexdigest()
    body = response.json()
    assert body["source_type"] == "markdown"
    assert body["size_bytes"] == len(MARKDOWN_BYTES)

    # Raw preserved byte-for-byte under the .md filename ...
    assert aws_backends["storage"].get_object(f"raw/{sha}/source.md") == (
        MARKDOWN_BYTES
    )
    # ... while the artifact is the rendered, shell-wrapped HTML document.
    artifact = aws_backends["storage"].get_object(f"artifacts/{sha}/index.html")
    assert artifact is not None and artifact != MARKDOWN_BYTES
    assert artifact.startswith(b"<!doctype html>")
    assert b"<title>notes.md</title>" in artifact
    assert b"<h1>Title</h1>" in artifact
    # Raw/unsafe HTML in the Markdown survives (renderer is intentionally raw).
    assert b"<b>raw</b>" in artifact


def test_finalize_dedupes_identical_bytes_to_one_canonical_item(
    client, aws_backends, signer
):
    sha = hashlib.sha256(HTML_BYTES).hexdigest()

    _, first = _upload_and_finalize(
        client, signer, aws_backends, data=HTML_BYTES, filename="demo.html"
    )
    assert first.status_code == 200, first.text

    second_id, second = _upload_and_finalize(
        client, signer, aws_backends, data=HTML_BYTES, filename="other.html"
    )
    assert second.status_code == 200, second.text

    # Deduped to the original canonical item (filename is the FIRST upload's).
    assert second.json()["sha256"] == sha
    assert second.json()["original_filename"] == "demo.html"

    # Exactly one list item; the duplicate's temp object was still removed.
    assert len(_list_items(aws_backends)) == 1
    assert aws_backends["storage"].get_object(f"tmp/{second_id}") is None


def test_dedupe_keys_off_metadata_not_s3_raw_exists(client, aws_backends, signer):
    # Simulate a crashed prior finalize: raw object present in S3, but NO
    # metadata item. Finalize must NOT falsely dedupe — it must write metadata.
    sha = hashlib.sha256(HTML_BYTES).hexdigest()
    _put_temp(aws_backends, f"raw/{sha}/source.html", HTML_BYTES)
    assert aws_backends["repo"].get_content_item(sha) is None

    _, response = _upload_and_finalize(
        client, signer, aws_backends, data=HTML_BYTES, filename="demo.html"
    )
    assert response.status_code == 200, response.text
    assert aws_backends["repo"].get_content_item(sha) is not None
    assert len(_list_items(aws_backends)) == 1


# --------------------------------------------------------------------------- #
# Rejections
# --------------------------------------------------------------------------- #


def test_missing_session_rejected(client, signer):
    response = _finalize(client, signer, "does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "upload_not_found"


def test_expired_session_rejected(client, aws_backends, signer):
    presigned = _presign(client, signer, filename="demo.html")
    _put_temp(aws_backends, presigned["fields"]["key"], HTML_BYTES)

    # Rewrite the session item with a past TTL (finalize must not rely on
    # DynamoDB's lazy TTL deletion).
    aws_backends["ddb"].Table(TABLE_NAME).update_item(
        Key={"pk": f"UPLOAD#{presigned['upload_id']}", "sk": "META"},
        UpdateExpression="SET expires_at_epoch = :e",
        ExpressionAttributeValues={":e": int(time.time()) - 1},
    )

    response = _finalize(client, signer, presigned["upload_id"])
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "upload_expired"


def test_missing_temp_object_rejected(client, signer):
    # Session exists (presign), but the browser never uploaded the object.
    presigned = _presign(client, signer, filename="demo.html")
    response = _finalize(client, signer, presigned["upload_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "upload_not_uploaded"


def test_oversize_rejected_by_head_gate_and_temp_survives(client, aws_backends, signer):
    presigned = _presign(client, signer, filename="demo.html")
    key = presigned["fields"]["key"]
    _put_temp(aws_backends, key, b"a" * (MAX_UPLOAD_BYTES + 1))

    response = _finalize(client, signer, presigned["upload_id"])
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"
    # The temp object is left intact (the failure is observed before any
    # cleanup), so the finalize never strands or half-processes state.
    assert _object_exists(aws_backends, key)


def test_invalid_utf8_rejected(client, aws_backends, signer):
    presigned = _presign(client, signer, filename="demo.html")
    _put_temp(aws_backends, presigned["fields"]["key"], b"\xff\xfe\x00bad")
    response = _finalize(client, signer, presigned["upload_id"])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_utf8"


def test_unsupported_stored_source_type_rejected(client, aws_backends, signer):
    # A corrupted session carrying a non-v1 source type must be rejected from
    # the stored value (finalize never re-derives type from the request body).
    upload_id = "corrupt-session-0001"
    aws_backends["ddb"].Table(TABLE_NAME).put_item(
        Item={
            "pk": f"UPLOAD#{upload_id}",
            "sk": "META",
            "item_type": "upload_session",
            "upload_id": upload_id,
            "created_by": OWNER_EMAIL,
            "original_filename": "mystery.bin",
            "source_type": "binary",
            "tmp_key": f"tmp/{upload_id}",
            "max_size_bytes": MAX_UPLOAD_BYTES,
            "created_at": "2026-01-01T00:00:00Z",
            "expires_at_epoch": int(time.time()) + 3600,
        }
    )
    response = _finalize(client, signer, upload_id)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_source_type"


def test_finalize_does_not_trust_client_filename_or_source_type(
    client, aws_backends, signer
):
    # The finalize body forbids extra fields: any attempt to assert a
    # filename/source_type is rejected outright.
    presigned = _presign(client, signer, filename="demo.html")
    _put_temp(aws_backends, presigned["fields"]["key"], HTML_BYTES)
    response = client.post(
        "/api/uploads/finalize",
        headers=_headers(signer),
        json={
            "upload_id": presigned["upload_id"],
            "original_filename": "evil.md",
            "source_type": "markdown",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --------------------------------------------------------------------------- #
# Boundary guards (CSRF / auth / host) hold for finalize too
# --------------------------------------------------------------------------- #


def test_missing_csrf_rejected(client, aws_backends, signer):
    presigned = _presign(client, signer, filename="demo.html")
    _put_temp(aws_backends, presigned["fields"]["key"], HTML_BYTES)
    response = _finalize(client, signer, presigned["upload_id"], csrf=False)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unauthenticated_finalize_rejected(client):
    response = client.post(
        "/api/uploads/finalize",
        headers={
            "host": LOCAL_DASHBOARD_HOST,
            "Origin": LOCAL_DASHBOARD_ORIGIN,
            "X-Share-CSRF": "1",
        },
        json={"upload_id": "whatever"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_finalize_not_routable_on_private_host(client, signer):
    response = _finalize(client, signer, "whatever", host=PRIVATE_HOST)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "route_not_allowed"
