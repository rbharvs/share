"""The Access token verifier — the deep module that gates every private route.

``AccessVerifier.verify(token, host) -> Principal`` is a single funnel: it picks
the per-host :class:`AccessConfig`, rejects unsupported algorithms *before* any
key lookup (defeating ``alg=none`` and RS/HS confusion), resolves the signing key
through the injected :class:`JwksProvider`, and runs one ``jwt.decode`` that
checks signature + issuer + audience + expiry + required claims. The email claim
is then matched against the owner allowlist. Every failure fails closed and maps
onto a slice-01 domain error (``auth_required`` / ``auth_invalid`` /
``host_not_allowed``).

The verification code is byte-identical for Cloudflare-minted and locally-minted
tokens; only the injected ``AccessConfig`` differs.
"""

from __future__ import annotations

import jwt
from jwt.exceptions import PyJWTError

from share.errors import AuthInvalidError, AuthRequiredError, HostNotAllowedError
from share.hosts import HostKind

from .jwks import JwksProvider
from .models import AccessConfig, Principal

#: RS256 only. Passed to ``jwt.decode`` *and* checked against the token header
#: before key lookup, so ``alg=none`` and HS/RS confusion are rejected early.
ALLOWED_ALGS = ["RS256"]

#: Claims ``jwt.decode`` must find present (independent of their values).
REQUIRED_CLAIMS = ["exp", "iss", "aud"]


class AccessVerifier:
    """Verifies a ``Cf-Access-Jwt-Assertion`` value for a given host kind."""

    def __init__(
        self,
        configs: dict[HostKind, AccessConfig],
        jwks_provider: JwksProvider,
        *,
        leeway: float = 60.0,
    ) -> None:
        self._configs = dict(configs)
        self._jwks = jwks_provider
        self._leeway = leeway

    def verify(self, token: str | None, host: HostKind) -> Principal:
        config = self._configs.get(host)
        if config is None:
            # No Access config for this host kind (e.g. public/unknown): a
            # private credential has no meaning here.
            raise HostNotAllowedError()

        if not token:
            raise AuthRequiredError()

        # Inspect the header WITHOUT trusting it, purely to reject bad algorithms
        # and obtain the kid before any key material is touched.
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError as exc:
            raise AuthInvalidError("Token header is malformed.") from exc

        if header.get("alg") not in ALLOWED_ALGS:
            # Rejects alg=none and HS/RS confusion *before* key lookup.
            raise AuthInvalidError("Token algorithm is not allowed.")

        kid = header.get("kid")
        if not kid:
            raise AuthInvalidError("Token is missing a key id.")

        key = self._jwks.signing_key(config.jwks_url, kid)

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=ALLOWED_ALGS,
                audience=config.audience,
                issuer=config.issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except PyJWTError as exc:
            # Bad signature, wrong issuer/audience, expired, or a missing
            # required claim all collapse to one closed-door error.
            raise AuthInvalidError() from exc

        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise AuthInvalidError("Token is missing the email claim.")
        if email.strip().lower() != config.allowed_email.strip().lower():
            raise AuthInvalidError("Token email is not allowed.")

        return Principal(
            email=email.strip().lower(),
            host=host,
            audience=config.audience,
            issuer=config.issuer,
            subject=claims.get("sub"),
        )


def access_configs(settings: object) -> dict[HostKind, AccessConfig]:
    """Build the per-host :class:`AccessConfig` map from settings.

    Both private hosts share issuer/JWKS but carry distinct audiences. Only the
    two private host kinds get a config; public/unknown intentionally get none,
    so :meth:`AccessVerifier.verify` rejects them with ``host_not_allowed``.
    """

    return {
        HostKind.DASHBOARD: AccessConfig(
            issuer=settings.access_issuer,  # type: ignore[attr-defined]
            audience=settings.dashboard_audience,  # type: ignore[attr-defined]
            jwks_url=settings.jwks_url,  # type: ignore[attr-defined]
            allowed_email=settings.allowed_owner_email,  # type: ignore[attr-defined]
        ),
        HostKind.PRIVATE_CONTENT: AccessConfig(
            issuer=settings.access_issuer,  # type: ignore[attr-defined]
            audience=settings.private_audience,  # type: ignore[attr-defined]
            jwks_url=settings.jwks_url,  # type: ignore[attr-defined]
            allowed_email=settings.allowed_owner_email,  # type: ignore[attr-defined]
        ),
    }
