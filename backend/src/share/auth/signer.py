"""Local Access-compatible signer.

``LocalAccessSigner`` mints fresh Cloudflare-shaped RS256 JWTs (one per request)
and serves the matching JWKS document. It proves the verifier accepts
locally-minted tokens through the *identical* code path used for real Cloudflare
Access tokens — there is no auth bypass, only a different key/issuer/audience.

The browser reverse-proxy that *forwards* these tokens as a
``Cf-Access-Jwt-Assertion`` header is deferred to slice 09 (where Vite exists);
this is the token mint + JWKS core only.

``sign_raw`` exists to mint deliberately-malformed tokens (missing claims, wrong
algorithm, foreign key) so the verifier's rejection paths can be exercised.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from jwt.algorithms import RSAAlgorithm

DEFAULT_KID = "local-access-signing-key"


class LocalAccessSigner:
    """Mints RS256 tokens and publishes the corresponding JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_email: str,
        kid: str = DEFAULT_KID,
        private_key: RSAPrivateKey | None = None,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._email = allowed_email
        self._kid = kid
        self._now = now_fn
        self._private_key = private_key or rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )

    @property
    def kid(self) -> str:
        return self._kid

    @property
    def public_key(self):
        return self._private_key.public_key()

    def jwks(self) -> dict[str, Any]:
        """The public JWKS document this signer's tokens verify against."""

        jwk = json.loads(RSAAlgorithm.to_jwk(self.public_key))
        jwk.update({"kid": self._kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def claims(
        self,
        *,
        email: str | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        expires_in: int = 3600,
        issued_at: int | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a Cloudflare-shaped claim set (fresh nonce/sub per call)."""

        iat = int(issued_at if issued_at is not None else self._now())
        payload: dict[str, Any] = {
            "iss": issuer if issuer is not None else self._issuer,
            "aud": [audience if audience is not None else self._audience],
            "email": email if email is not None else self._email,
            "sub": uuid.uuid4().hex,
            "iat": iat,
            "nbf": iat,
            "exp": iat + expires_in,
            "identity_nonce": uuid.uuid4().hex,
        }
        if extra_claims:
            payload.update(extra_claims)
        return payload

    def sign(self, **kwargs: Any) -> str:
        """Mint a fresh, valid RS256 token. ``kwargs`` go to :meth:`claims`."""

        kid = kwargs.pop("kid", self._kid)
        return self.sign_raw(self.claims(**kwargs), kid=kid)

    def sign_raw(
        self,
        claims: dict[str, Any],
        *,
        kid: str | None = None,
        algorithm: str = "RS256",
        key: Any = None,
    ) -> str:
        """Mint a token from an explicit claim set — used for adversarial cases."""

        headers = {"kid": kid if kid is not None else self._kid}
        signing_key = key if key is not None else self._private_key
        return jwt.encode(claims, signing_key, algorithm=algorithm, headers=headers)
