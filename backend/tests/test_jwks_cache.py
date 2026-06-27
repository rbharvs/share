"""Tests for the JWKS cache: fetch-once, TTL expiry, rotation recovery, and the
module-level provider reused across warm invocations.
"""

from __future__ import annotations

import pytest

from conftest import DASHBOARD_AUDIENCE, ISSUER, JWKS_URL, OWNER_EMAIL
from share.auth import CachingJwksProvider, LocalAccessSigner, caching_jwks_provider
from share.errors import AuthInvalidError


def _counting_fetch(state: dict):
    def fetch(url: str) -> dict:
        state["n"] += 1
        return state["jwks"]

    return fetch


def test_jwks_fetched_once_then_served_from_cache(signer):
    state = {"n": 0, "jwks": signer.jwks()}
    provider = CachingJwksProvider(fetch=_counting_fetch(state), ttl_seconds=1000)

    for _ in range(5):
        provider.signing_key(JWKS_URL, signer.kid)

    assert state["n"] == 1


def test_ttl_expiry_triggers_refetch(signer):
    clock = {"t": 0.0}
    state = {"n": 0, "jwks": signer.jwks()}
    provider = CachingJwksProvider(
        fetch=_counting_fetch(state),
        ttl_seconds=100,
        time_fn=lambda: clock["t"],
    )

    provider.signing_key(JWKS_URL, signer.kid)  # cold fetch
    clock["t"] = 50
    provider.signing_key(JWKS_URL, signer.kid)  # still fresh
    assert state["n"] == 1

    clock["t"] = 150  # past TTL
    provider.signing_key(JWKS_URL, signer.kid)
    assert state["n"] == 2


def test_key_rotation_force_refresh_recovers(signer):
    rotated = LocalAccessSigner(
        issuer=ISSUER,
        audience=DASHBOARD_AUDIENCE,
        allowed_email=OWNER_EMAIL,
        kid="rotated-signing-key",
    )
    state = {"n": 0, "jwks": signer.jwks()}
    provider = CachingJwksProvider(fetch=_counting_fetch(state), ttl_seconds=1000)

    provider.signing_key(JWKS_URL, signer.kid)  # caches original key set
    assert state["n"] == 1

    # The origin rotates its keys; the cache is still warm with the old set.
    state["jwks"] = rotated.jwks()
    key = provider.signing_key(JWKS_URL, rotated.kid)  # unknown kid -> refresh
    assert key is not None
    assert state["n"] == 2  # exactly one forced refresh recovered the new key


def test_unknown_kid_refreshes_once_then_fails_closed(signer):
    state = {"n": 0, "jwks": signer.jwks()}
    provider = CachingJwksProvider(fetch=_counting_fetch(state), ttl_seconds=1000)

    with pytest.raises(AuthInvalidError):
        provider.signing_key(JWKS_URL, "permanently-unknown-kid")

    assert state["n"] == 2  # initial fetch + one forced refresh, then reject


def test_module_level_provider_reuses_cache_across_warm_invocations(signer):
    # One CachingJwksProvider instance simulates a warm Lambda: many lookups, one
    # fetch. The module-level singleton is exactly this shape.
    state = {"n": 0, "jwks": signer.jwks()}
    provider = CachingJwksProvider(fetch=_counting_fetch(state))
    for _ in range(10):  # warm invocations
        provider.signing_key(JWKS_URL, signer.kid)
    assert state["n"] == 1

    assert isinstance(caching_jwks_provider, CachingJwksProvider)
