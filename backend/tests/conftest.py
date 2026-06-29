from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from share.api import create_app
from share.auth import (
    AccessConfig,
    AccessVerifier,
    LocalAccessSigner,
    StaticJwksProvider,
)
from share.hosts import HostKind

DASHBOARD_HOST = "share.example.com"
PRIVATE_HOST = "private.usercontent.example"
PUBLIC_HOST = "public.usercontent.example"

# --------------------------------------------------------------------------- #
# Shared moto (mock AWS) backend
#
# The full mock-AWS stack + DynamoDB table + both S3 buckets are expensive to
# stand up, so they are created ONCE per session (``_moto_aws``) rather than per
# test. Tests get a clean slate via the autouse ``_reset_moto_state`` fixture,
# which truncates the table and empties both buckets after each test instead of
# rebuilding the mock. The app under test never builds its own boto3 clients —
# repositories/storage are injected via ``dependency_overrides`` — so a single
# long-lived mock is safe and order-independent.
# --------------------------------------------------------------------------- #

# Shared names (identical schema/region across all moto test files). Both
# buckets are always created even though some files only use the private one —
# harmless and keeps the session backend uniform.
MOTO_REGION = "us-east-1"
TABLE_NAME = "share"
PRIVATE_BUCKET = "share-private"
PUBLIC_BUCKET = "share-public"


@dataclass
class MotoBackend:
    """Handles to the session-scoped moto AWS backend."""

    ddb_resource: Any
    ddb_client: Any
    s3_client: Any
    table_name: str = TABLE_NAME
    private_bucket: str = PRIVATE_BUCKET
    public_bucket: str = PUBLIC_BUCKET


@pytest.fixture(scope="session")
def _moto_aws() -> Iterator[MotoBackend]:
    """Enter ``mock_aws()`` once and provision the table + both buckets once."""

    with mock_aws():
        s3 = boto3.client("s3", region_name=MOTO_REGION)
        s3.create_bucket(Bucket=PRIVATE_BUCKET)
        s3.create_bucket(Bucket=PUBLIC_BUCKET)

        ddb = boto3.resource("dynamodb", region_name=MOTO_REGION)
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

        yield MotoBackend(
            ddb_resource=ddb,
            ddb_client=boto3.client("dynamodb", region_name=MOTO_REGION),
            s3_client=s3,
        )


@pytest.fixture(autouse=True)
def _reset_moto_state(request: pytest.FixtureRequest) -> Iterator[None]:
    """Truncate the table and empty both buckets after each moto-backed test.

    Autouse but cheap: it only does work for tests that actually pulled in the
    session backend (so non-moto tests pay nothing). Robust to an already-empty
    table/bucket so order/skip never strands state for the next test.
    """

    yield
    if "_moto_aws" not in request.fixturenames:
        return
    backend: MotoBackend = request.getfixturevalue("_moto_aws")

    table = backend.ddb_resource.Table(backend.table_name)
    scan_kwargs: dict[str, Any] = {"ProjectionExpression": "pk, sk"}
    with table.batch_writer() as batch:
        while True:
            page = table.scan(**scan_kwargs)
            for item in page.get("Items", []):
                batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            last = page.get("LastEvaluatedKey")
            if not last:
                break
            scan_kwargs["ExclusiveStartKey"] = last

    for bucket in (backend.private_bucket, backend.public_bucket):
        paginator = backend.s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                backend.s3_client.delete_objects(
                    Bucket=bucket, Delete={"Objects": keys}
                )


# Shared Access fixtures. The issuer/JWKS are shared across both private hosts;
# only the audience differs per host, so a token minted for one host is rejected
# on the other.
ISSUER = "https://team.cloudflareaccess.test"
DASHBOARD_AUDIENCE = "dashboard-audience-0000"
PRIVATE_AUDIENCE = "private-audience-1111"
OWNER_EMAIL = "owner@example.com"
JWKS_URL = "https://team.cloudflareaccess.test/cdn-cgi/access/certs"


# A minimal Vite-shaped built bundle: a hashed-name asset (Vite never emits a
# bare ``app.js`` — the build produces ``index-<hash>.js``) plus an index.html
# that references it. Host/route tests must exercise the REAL asset-serving path,
# so we inject this deterministic bundle rather than depending on the gitignored
# package ``static`` dir, whose presence/absence flips between the unbuilt
# placeholder and the real (hash-named) bundle and would otherwise make the suite
# pass or fail depending on whether ``mise run build`` has run.
_BUILT_ASSET_NAME = "index-test123.js"
_BUILT_ASSET_JS = "console.log('built dashboard bundle');"
_BUILT_INDEX_HTML = (
    "<!doctype html><html><head><title>share dashboard</title>"
    f'<script type="module" src="/assets/{_BUILT_ASSET_NAME}"></script></head>'
    '<body><div id="root"></div></body></html>'
)


@pytest.fixture
def built_static_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A deterministic built dashboard SPA bundle injected via ``static_dir``.

    Lets host/route tests exercise real static serving independent of whether the
    gitignored package ``static`` dir has been built. The asset name is hashed
    (Vite-shaped), so tests resolve it from ``index.html`` instead of guessing.
    """

    root = tmp_path_factory.mktemp("static")
    (root / "index.html").write_text(_BUILT_INDEX_HTML)
    assets = root / "assets"
    assets.mkdir()
    (assets / _BUILT_ASSET_NAME).write_text(_BUILT_ASSET_JS)
    return root


@pytest.fixture
def client(built_static_dir: Path) -> TestClient:
    # raise_server_exceptions=False so handler-mapped errors are observed as
    # real HTTP responses rather than re-raised exceptions. The bundle is injected
    # so the dashboard SPA/asset surface is served from a known built state.
    return TestClient(
        create_app(static_dir=built_static_dir), raise_server_exceptions=False
    )


@pytest.fixture
def signer() -> LocalAccessSigner:
    """A local signer standing in for the Cloudflare Access signing key."""

    return LocalAccessSigner(
        issuer=ISSUER, audience=DASHBOARD_AUDIENCE, allowed_email=OWNER_EMAIL
    )


@pytest.fixture
def access_config_map() -> dict[HostKind, AccessConfig]:
    """Per-host configs sharing one issuer/JWKS but distinct audiences."""

    return {
        HostKind.DASHBOARD: AccessConfig(
            issuer=ISSUER,
            audience=DASHBOARD_AUDIENCE,
            jwks_url=JWKS_URL,
            allowed_email=OWNER_EMAIL,
        ),
        HostKind.PRIVATE_CONTENT: AccessConfig(
            issuer=ISSUER,
            audience=PRIVATE_AUDIENCE,
            jwks_url=JWKS_URL,
            allowed_email=OWNER_EMAIL,
        ),
    }


@pytest.fixture
def verifier(
    signer: LocalAccessSigner,
    access_config_map: dict[HostKind, AccessConfig],
) -> AccessVerifier:
    """A verifier whose JWKS is backed by the signer (no network)."""

    return AccessVerifier(
        access_config_map, StaticJwksProvider(signer.jwks()), leeway=10
    )
