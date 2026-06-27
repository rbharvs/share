"""Cloudflare Access JWT verification and the local Access-compatible signer.

The public surface is intentionally small: a verifier, its config/principal value
objects, pluggable JWKS providers, the FastAPI dependency that gates routes, and
the local signer used for development and tests.
"""

from .dependencies import (
    ACCESS_HEADER,
    get_access_verifier,
    require_principal,
)
from .jwks import (
    CachingJwksProvider,
    JwksProvider,
    StaticJwksProvider,
    caching_jwks_provider,
    urllib_fetch,
)
from .models import AccessConfig, Principal
from .signer import LocalAccessSigner
from .verifier import ALLOWED_ALGS, AccessVerifier, access_configs

__all__ = [
    "ACCESS_HEADER",
    "ALLOWED_ALGS",
    "AccessConfig",
    "AccessVerifier",
    "CachingJwksProvider",
    "JwksProvider",
    "LocalAccessSigner",
    "Principal",
    "StaticJwksProvider",
    "access_configs",
    "caching_jwks_provider",
    "get_access_verifier",
    "require_principal",
    "urllib_fetch",
]
