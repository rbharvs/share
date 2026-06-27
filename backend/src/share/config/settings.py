"""Settings / config DI provider.

Env-driven configuration. Prod and local config sets are swappable and never
co-deployed; there is no ``APP_ENV`` auth bypass — only the injected config
differs. The host registry mapping consumed by the gate is derived from these
hosts, so a single config swap re-points every host boundary.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from share.hosts import HostKind


class Settings(BaseSettings):
    """Application settings, sourced from the environment (``SHARE_`` prefix)."""

    model_config = SettingsConfigDict(env_prefix="SHARE_", extra="ignore")

    # Host boundaries.
    dashboard_host: str = "share.example.com"
    private_host: str = "private.usercontent.example"
    public_host: str = "public.usercontent.example"

    # The exact dashboard Origin accepted by CSRF/Origin checks (later slices).
    dashboard_origin: str = "https://share.example.com"

    # Owner allowlist — plain lowercased string compare (no pydantic[email]).
    allowed_owner_email: str = "owner@example.com"

    # Per-host Access verification placeholders (populated in later slices).
    access_issuer: str = ""
    dashboard_audience: str = ""
    private_audience: str = ""
    jwks_url: str = ""

    # AWS resources.
    region: str = "us-east-1"
    table_name: str = "share"
    private_bucket: str = "share-private"
    public_bucket: str = "share-public"

    def host_kinds(self) -> dict[str, HostKind]:
        """Build the host registry mapping from configured hosts.

        This is the single source of truth the gate consumes, so swapping the
        host config (prod vs. local) re-points every host boundary at once.
        """

        return {
            self.dashboard_host.lower(): HostKind.DASHBOARD,
            self.private_host.lower(): HostKind.PRIVATE_CONTENT,
            self.public_host.lower(): HostKind.PUBLIC_CONTENT,
        }

    @classmethod
    def for_local(cls, **overrides: object) -> Settings:
        """Local-dev config: dev hosts/origin with their ports.

        Never co-deployed with prod — this is the swappable local mapping. The
        production default (the bare ``Settings()`` constructor) carries only
        the production hosts, so the dev hosts can never be a production
        fallback.
        """

        base: dict[str, object] = {
            "dashboard_host": "share.localhost:5174",
            "private_host": "private.localhost:5175",
            "public_host": "public.localhost:5176",
            "dashboard_origin": "http://share.localhost:5174",
        }
        base.update(overrides)
        return cls(**base)  # type: ignore[arg-type]


@lru_cache
def get_settings() -> Settings:
    """Cached settings provider used as the default DI dependency."""

    return Settings()
