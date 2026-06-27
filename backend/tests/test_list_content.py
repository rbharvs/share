"""End-to-end tests for ``GET /api/content`` (newest-first cursor pagination).

The dashboard spine runs: host gate -> Access auth -> listing service -> a
DynamoDB ``Query`` over the ``USER#default`` partition. moto backs DynamoDB; the
network-backed Access verifier is swapped for the conftest static one. Items are
seeded directly through the repository (the same two-item transaction finalize
uses) so ordering is deterministic and the read-side is exercised in isolation.
"""

from __future__ import annotations

import base64
import json

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from conftest import DASHBOARD_AUDIENCE
from share.api import create_app
from share.config import Settings
from share.content import ContentItem, ContentStatus, SourceType
from share.repository import DynamoMetadataRepository, MetadataRepository
from share.upload import UploadSession, get_repo

LOCAL_DASHBOARD_HOST = "share.localhost:5174"
PRIVATE_HOST = "private.localhost:5175"
OWNER_EMAIL = "owner@example.com"
TABLE_NAME = "share"

# The content hosts the app under test (Settings.for_local) builds URLs from.
CONTENT_PRIVATE_HOST = "private.localhost:5175"
CONTENT_PUBLIC_HOST = "public.localhost:5176"


@pytest.fixture
def repo():
    """A moto-backed DynamoDB table and the matching repository adapter."""

    with mock_aws():
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
        yield DynamoMetadataRepository(
            table_name=TABLE_NAME,
            resource=ddb,
            client=boto3.client("dynamodb", region_name="us-east-1"),
        )


@pytest.fixture
def list_app(repo, verifier):
    app = create_app(Settings.for_local())
    app.state.access_verifier = verifier
    app.dependency_overrides[get_repo] = lambda: repo
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(list_app) -> TestClient:
    return TestClient(list_app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _sha(n: int) -> str:
    """A deterministic, realistic 64-hex-char SHA for the n-th seeded item."""

    return f"{n:064x}"


def _seed(
    repo: MetadataRepository,
    *,
    n: int,
    created_at: str,
    status: ContentStatus = ContentStatus.UPLOADED,
    public_key: str | None = None,
    published_at: str | None = None,
) -> ContentItem:
    sha = _sha(n)
    item = ContentItem(
        sha256=sha,
        source_type=SourceType.HTML,
        original_filename=f"demo-{n}.html",
        size_bytes=10 + n,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        published_at=published_at,
        created_by=OWNER_EMAIL,
        raw_key=f"raw/{sha}/source.html",
        private_artifact_key=f"artifacts/{sha}/index.html",
        public_key=public_key,
        last_upload_id=f"u-{n}",
    )
    repo.put_content_item(item)
    return item


def _ts(i: int) -> str:
    """Millisecond-resolution timestamps, ascending in i (newest = highest)."""

    return f"2026-06-24T17:52:{i // 1000:02d}.{i % 1000:03d}Z"


def _auth_headers(signer):
    # A read-only GET: dashboard host + a valid Access token, no CSRF/Origin.
    return {
        "host": LOCAL_DASHBOARD_HOST,
        "Cf-Access-Jwt-Assertion": signer.sign(audience=DASHBOARD_AUDIENCE),
    }


def _list(client, signer, **params):
    return client.get(
        "/api/content", headers=_auth_headers(signer), params=params
    )


# --------------------------------------------------------------------------- #
# Listing shape & ordering
# --------------------------------------------------------------------------- #


def test_empty_listing_returns_empty_items_and_null_cursor(client, signer):
    response = _list(client, signer)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_lists_newest_first_with_common_item_shape(client, repo, signer):
    # Seed in ascending time; newest (highest ts) must come back first.
    for i in (1, 2, 3):
        _seed(repo, n=i, created_at=_ts(i))

    response = _list(client, signer)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None

    shas = [item["sha256"] for item in body["items"]]
    assert shas == [_sha(3), _sha(2), _sha(1)]  # newest-first

    newest = body["items"][0]
    assert newest["short_sha"] == _sha(3)[:12]
    assert newest["status"] == "uploaded"
    assert newest["published_at"] is None
    assert newest["private_url"] == f"https://{CONTENT_PRIVATE_HOST}/u/{_sha(3)}"
    assert newest["public_url"] is None  # null unless published


def test_published_item_exposes_public_url(client, repo, signer):
    sha = _sha(7)
    _seed(
        repo,
        n=7,
        created_at=_ts(7),
        status=ContentStatus.PUBLISHED,
        public_key=f"public/{sha}/index.html",
        published_at=_ts(7),
    )
    body = _list(client, signer).json()
    item = body["items"][0]
    assert item["status"] == "published"
    assert item["public_url"] == f"https://{CONTENT_PUBLIC_HOST}/u/{sha}"
    assert item["private_url"] == f"https://{CONTENT_PRIVATE_HOST}/u/{sha}"


def test_listing_reads_only_user_default_partition(client, repo, signer):
    # put_content_item writes BOTH a CONTENT#{sha}/META lookup item and a
    # USER#default list item; an upload session lives in yet another partition.
    # If the listing scanned, the count would balloon past the seeded items.
    for i in (1, 2):
        _seed(repo, n=i, created_at=_ts(i))
    repo.create_upload_session(  # noise in the UPLOAD# partition
        UploadSession(
            upload_id="noise",
            created_by=OWNER_EMAIL,
            original_filename="x.html",
            source_type=SourceType.HTML,
            tmp_key="tmp/noise",
            max_size_bytes=1,
            created_at=_ts(9),
            expires_at_epoch=1,
        )
    )
    body = _list(client, signer).json()
    assert len(body["items"]) == 2  # only the two list-partition items


# --------------------------------------------------------------------------- #
# Cursor pagination
# --------------------------------------------------------------------------- #


def test_cursor_is_opaque_base64url_of_dynamo_pagination_state(
    client, repo, signer
):
    for i in (1, 2, 3):
        _seed(repo, n=i, created_at=_ts(i))

    body = _list(client, signer, limit=2).json()
    assert len(body["items"]) == 2
    cursor = body["next_cursor"]
    assert isinstance(cursor, str) and cursor

    # Opaque to clients, but internally a base64url DynamoDB LastEvaluatedKey.
    decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    assert decoded["pk"] == "USER#default"
    assert "sk" in decoded


def test_second_page_resumes_with_no_overlap(client, repo, signer):
    for i in (1, 2, 3):
        _seed(repo, n=i, created_at=_ts(i))

    first = _list(client, signer, limit=2).json()
    page1 = [item["sha256"] for item in first["items"]]
    assert page1 == [_sha(3), _sha(2)]
    assert first["next_cursor"] is not None

    second = _list(client, signer, limit=2, cursor=first["next_cursor"]).json()
    page2 = [item["sha256"] for item in second["items"]]
    assert page2 == [_sha(1)]
    assert second["next_cursor"] is None

    # No overlap, and together they are the full newest-first listing.
    assert set(page1).isdisjoint(page2)
    assert page1 + page2 == [_sha(3), _sha(2), _sha(1)]


def test_full_walk_via_cursor_covers_every_item_once(client, repo, signer):
    count = 5
    for i in range(1, count + 1):
        _seed(repo, n=i, created_at=_ts(i))

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        body = _list(client, signer, **params).json()
        seen.extend(item["sha256"] for item in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
        assert pages < 10  # guard against a non-terminating walk

    assert seen == [_sha(i) for i in range(count, 0, -1)]  # newest-first
    assert len(seen) == len(set(seen)) == count  # every item exactly once


# --------------------------------------------------------------------------- #
# Validation & boundary guards
# --------------------------------------------------------------------------- #


def test_invalid_cursor_rejected(client, signer):
    response = _list(client, signer, cursor="not-a-valid-cursor")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_out_of_range_limit_rejected(client, signer, limit):
    response = _list(client, signer, limit=limit)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_unauthenticated_listing_rejected(client):
    response = client.get(
        "/api/content", headers={"host": LOCAL_DASHBOARD_HOST}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_required"


def test_listing_not_routable_on_private_host(client, signer):
    response = client.get(
        "/api/content",
        headers={
            "host": PRIVATE_HOST,
            "Cf-Access-Jwt-Assertion": signer.sign(
                audience=DASHBOARD_AUDIENCE
            ),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "route_not_allowed"
