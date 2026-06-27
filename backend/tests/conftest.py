from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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

# Shared Access fixtures. The issuer/JWKS are shared across both private hosts;
# only the audience differs per host, so a token minted for one host is rejected
# on the other.
ISSUER = "https://team.cloudflareaccess.test"
DASHBOARD_AUDIENCE = "dashboard-audience-0000"
PRIVATE_AUDIENCE = "private-audience-1111"
OWNER_EMAIL = "owner@example.com"
JWKS_URL = "https://team.cloudflareaccess.test/cdn-cgi/access/certs"


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False so handler-mapped errors are observed as
    # real HTTP responses rather than re-raised exceptions.
    return TestClient(create_app(), raise_server_exceptions=False)


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
