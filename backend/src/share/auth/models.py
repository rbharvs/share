"""Auth value objects: the per-host verification config and the verified
principal.

Both are immutable Pydantic models. ``AccessConfig`` is the *only* thing that
differs between production (Cloudflare-minted tokens) and local development
(``LocalAccessSigner``-minted tokens): the verification code path is identical,
so a local-issuer token is rejected on a prod-configured host purely because the
injected ``issuer``/``audience``/``jwks_url`` differ.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from share.hosts import HostKind


class AccessConfig(BaseModel):
    """Per-host Cloudflare Access verification parameters.

    ``issuer`` and ``jwks_url`` are typically shared by both private hosts (one
    team domain), while ``audience`` is host-specific so a token minted for the
    dashboard Access app is rejected on the private-content host and vice versa.
    ``allowed_email`` is the owner allowlist, compared as a lowercased string.
    """

    model_config = ConfigDict(frozen=True)

    issuer: str
    audience: str
    jwks_url: str
    allowed_email: str


class Principal(BaseModel):
    """An authenticated owner, produced only by a fully-verified token."""

    model_config = ConfigDict(frozen=True)

    email: str
    host: HostKind
    audience: str
    issuer: str
    subject: str | None = None
