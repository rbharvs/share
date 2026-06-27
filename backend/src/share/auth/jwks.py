"""JWKS provision: the signing-key lookup behind the verifier.

A :class:`JwksProvider` resolves ``(jwks_url, kid) -> PyJWK``. Two implementations:

- :class:`CachingJwksProvider` — the production provider. It fetches a JWKS once
  (per cold start), serves it from a TTL cache across warm invocations, and
  force-refreshes exactly once on an unknown ``kid`` so a Cloudflare key rotation
  self-heals without restarting the Lambda. The HTTP fetch is *injected* so the
  transport stays out of the cache logic and is trivially fakeable in tests.
- :class:`StaticJwksProvider` — a fixed in-memory key set for tests; no network.

A module-level :data:`caching_jwks_provider` singleton is the shared instance the
app wires in, so the JWKS cache survives across warm Lambda invocations.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from jwt import PyJWK, PyJWKSet

from share.errors import AuthInvalidError

#: A function that fetches and parses a JWKS document from a URL. Injected into
#: :class:`CachingJwksProvider` so the transport is swappable in tests.
JwksFetch = Callable[[str], dict[str, Any]]


class JwksProvider(Protocol):
    """Resolves a signing key for a ``kid`` advertised by a token header."""

    def signing_key(self, jwks_url: str, kid: str) -> PyJWK:
        """Return the :class:`PyJWK` for ``kid``, or raise ``AuthInvalidError``."""
        ...


def urllib_fetch(jwks_url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Default JWKS transport: a stdlib HTTPS GET returning the parsed JSON."""

    with urllib.request.urlopen(jwks_url, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _find(keyset: PyJWKSet, kid: str) -> PyJWK | None:
    for key in keyset.keys:
        if key.key_id == kid:
            return key
    return None


@dataclass
class _CacheEntry:
    keyset: PyJWKSet
    fetched_at: float


class CachingJwksProvider:
    """TTL-cached JWKS provider with key-rotation recovery.

    One fetch populates the cache; subsequent lookups within ``ttl_seconds``
    reuse it. An unknown ``kid`` triggers a single forced refresh (a rotation may
    have published new keys) and is rejected only if it is still absent.
    """

    def __init__(
        self,
        fetch: JwksFetch,
        *,
        ttl_seconds: float = 600.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._time = time_fn
        self._cache: dict[str, _CacheEntry] = {}

    def _load(self, jwks_url: str, *, force: bool = False) -> _CacheEntry:
        now = self._time()
        entry = self._cache.get(jwks_url)
        if force or entry is None or (now - entry.fetched_at) >= self._ttl:
            keyset = PyJWKSet.from_dict(self._fetch(jwks_url))
            entry = _CacheEntry(keyset=keyset, fetched_at=now)
            self._cache[jwks_url] = entry
        return entry

    def signing_key(self, jwks_url: str, kid: str) -> PyJWK:
        key = _find(self._load(jwks_url).keyset, kid)
        if key is None:
            # Unknown kid against a (possibly stale) cache: force one refresh to
            # recover from a key rotation before failing closed.
            key = _find(self._load(jwks_url, force=True).keyset, kid)
        if key is None:
            raise AuthInvalidError("Token signing key is not recognized.")
        return key


class StaticJwksProvider:
    """A fixed JWKS for tests — no network, ``jwks_url`` is ignored."""

    def __init__(self, jwks: dict[str, Any]) -> None:
        self._keyset = PyJWKSet.from_dict(jwks)

    def signing_key(self, jwks_url: str, kid: str) -> PyJWK:
        key = _find(self._keyset, kid)
        if key is None:
            raise AuthInvalidError("Token signing key is not recognized.")
        return key


#: Shared production provider. Module-level so the JWKS cache is reused across
#: warm Lambda invocations (one fetch per cold start).
caching_jwks_provider = CachingJwksProvider(fetch=urllib_fetch)
