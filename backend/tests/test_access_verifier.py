"""Behavioural tests for ``AccessVerifier.verify`` against a static JWKS.

Covers every PRD auth case: valid accepted; missing / bad-sig / wrong-iss /
wrong-aud / expired / wrong-email / missing-claim / unknown-kid / alg=none
rejected; dashboard-audience-on-private-host and private-audience-on-dashboard
both rejected; local-issuer rejected on a prod-configured host.
"""

from __future__ import annotations

import jwt
import pytest

from conftest import (
    DASHBOARD_AUDIENCE,
    ISSUER,
    JWKS_URL,
    OWNER_EMAIL,
    PRIVATE_AUDIENCE,
)
from share.auth import (
    AccessConfig,
    AccessVerifier,
    LocalAccessSigner,
    StaticJwksProvider,
)
from share.errors import AuthInvalidError, AuthRequiredError, HostNotAllowedError
from share.hosts import HostKind

# --- Happy paths -----------------------------------------------------------


def test_valid_dashboard_token_accepted(verifier, signer):
    token = signer.sign(audience=DASHBOARD_AUDIENCE)
    principal = verifier.verify(token, HostKind.DASHBOARD)
    assert principal.email == OWNER_EMAIL
    assert principal.host is HostKind.DASHBOARD
    assert principal.audience == DASHBOARD_AUDIENCE
    assert principal.issuer == ISSUER
    assert principal.subject  # Cloudflare-shaped sub present


def test_valid_private_token_accepted(verifier, signer):
    token = signer.sign(audience=PRIVATE_AUDIENCE)
    principal = verifier.verify(token, HostKind.PRIVATE_CONTENT)
    assert principal.email == OWNER_EMAIL
    assert principal.host is HostKind.PRIVATE_CONTENT
    assert principal.audience == PRIVATE_AUDIENCE


def test_email_claim_is_lowercased_and_compared_case_insensitively(verifier, signer):
    token = signer.sign(email="Owner@Example.com")
    principal = verifier.verify(token, HostKind.DASHBOARD)
    assert principal.email == OWNER_EMAIL


def test_verify_is_identical_path_for_cloudflare_and_local_tokens(
    access_config_map,
):
    # Two independent signers stand in for "Cloudflare" and "local". The exact
    # same verify() accepts both — only the injected AccessConfig differs.
    cloudflare = LocalAccessSigner(
        issuer=ISSUER, audience=DASHBOARD_AUDIENCE, allowed_email=OWNER_EMAIL
    )
    local = LocalAccessSigner(
        issuer=ISSUER, audience=DASHBOARD_AUDIENCE, allowed_email=OWNER_EMAIL
    )
    for signer in (cloudflare, local):
        verifier = AccessVerifier(
            access_config_map, StaticJwksProvider(signer.jwks()), leeway=10
        )
        principal = verifier.verify(signer.sign(), HostKind.DASHBOARD)
        assert principal.email == OWNER_EMAIL


# --- Rejection cases -------------------------------------------------------


def test_missing_token_is_auth_required(verifier):
    with pytest.raises(AuthRequiredError):
        verifier.verify(None, HostKind.DASHBOARD)
    with pytest.raises(AuthRequiredError):
        verifier.verify("", HostKind.DASHBOARD)


def test_bad_signature_rejected(verifier, signer):
    # A different key, same kid: signature won't verify against the published key.
    forger = LocalAccessSigner(
        issuer=ISSUER,
        audience=DASHBOARD_AUDIENCE,
        allowed_email=OWNER_EMAIL,
        kid=signer.kid,
    )
    token = forger.sign(audience=DASHBOARD_AUDIENCE)
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_wrong_issuer_rejected(verifier, signer):
    token = signer.sign(issuer="https://evil.cloudflareaccess.test")
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_wrong_audience_rejected(verifier, signer):
    token = signer.sign(audience="some-other-audience")
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_expired_token_rejected(verifier, signer):
    token = signer.sign(expires_in=-3600)  # expired an hour ago, past leeway
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_wrong_email_rejected(verifier, signer):
    token = signer.sign(email="intruder@example.com")
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_missing_email_claim_rejected(verifier, signer):
    claims = signer.claims()
    claims.pop("email")
    token = signer.sign_raw(claims)
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_missing_required_claim_rejected(verifier, signer):
    # Drop a required registered claim (exp): jwt.decode require=[...] rejects it.
    claims = signer.claims()
    claims.pop("exp")
    token = signer.sign_raw(claims)
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_unknown_kid_rejected(verifier, signer):
    token = signer.sign(kid="kid-not-in-jwks")
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_alg_none_rejected_before_key_lookup(access_config_map, signer):
    spy = _SpyProvider(StaticJwksProvider(signer.jwks()))
    verifier = AccessVerifier(access_config_map, spy, leeway=10)
    unsigned = jwt.encode(signer.claims(), key="", algorithm="none")
    with pytest.raises(AuthInvalidError):
        verifier.verify(unsigned, HostKind.DASHBOARD)
    assert spy.calls == 0  # never reached key lookup


def test_hs_rs_confusion_rejected_before_key_lookup(access_config_map, signer):
    # Classic alg-confusion attack: present an HS256-signed token to a verifier
    # that only trusts RS256. The verifier must reject on the algorithm before it
    # ever loads (and would otherwise HMAC-verify against) the RSA public key.
    spy = _SpyProvider(StaticJwksProvider(signer.jwks()))
    verifier = AccessVerifier(access_config_map, spy, leeway=10)
    token = signer.sign_raw(
        signer.claims(), algorithm="HS256", key="attacker-chosen-secret-32-bytes-min!"
    )
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)
    assert spy.calls == 0  # never reached key lookup


def test_garbage_token_rejected(verifier):
    with pytest.raises(AuthInvalidError):
        verifier.verify("not-a-jwt", HostKind.DASHBOARD)


# --- Host / audience crossover --------------------------------------------


def test_dashboard_audience_rejected_on_private_host(verifier, signer):
    token = signer.sign(audience=DASHBOARD_AUDIENCE)
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.PRIVATE_CONTENT)


def test_private_audience_rejected_on_dashboard_host(verifier, signer):
    token = signer.sign(audience=PRIVATE_AUDIENCE)
    with pytest.raises(AuthInvalidError):
        verifier.verify(token, HostKind.DASHBOARD)


def test_public_and_unknown_hosts_have_no_config(verifier, signer):
    token = signer.sign()
    for host in (HostKind.PUBLIC_CONTENT, HostKind.UNKNOWN):
        with pytest.raises(HostNotAllowedError):
            verifier.verify(token, host)


def test_local_issuer_rejected_on_prod_configured_host():
    # Only the injected AccessConfig differs: a local-issuer token, validly
    # signed by the local key, is rejected on a prod-issuer host purely on iss.
    local_signer = LocalAccessSigner(
        issuer="https://local.dev.test",
        audience=DASHBOARD_AUDIENCE,
        allowed_email=OWNER_EMAIL,
    )
    prod_configs = {
        HostKind.DASHBOARD: AccessConfig(
            issuer="https://prod-team.cloudflareaccess.com",
            audience=DASHBOARD_AUDIENCE,
            jwks_url=JWKS_URL,
            allowed_email=OWNER_EMAIL,
        )
    }
    # Prod host trusts the same key material (signature passes); only iss differs.
    verifier = AccessVerifier(
        prod_configs, StaticJwksProvider(local_signer.jwks()), leeway=10
    )
    with pytest.raises(AuthInvalidError):
        verifier.verify(local_signer.sign(), HostKind.DASHBOARD)


class _SpyProvider:
    """Wraps a provider and counts signing-key lookups."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    def signing_key(self, jwks_url, kid):
        self.calls += 1
        return self._inner.signing_key(jwks_url, kid)
