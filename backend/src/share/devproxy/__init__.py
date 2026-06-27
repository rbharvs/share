"""Local Access-compatible reverse proxy (slice 09).

Local-development only: never imported by the Lambda handler. Mints signed
``Cf-Access-Jwt-Assertion`` headers via :class:`~share.auth.LocalAccessSigner`
and forwards to Vite / FastAPI, so daily local dev exercises the real auth path
without an auth-disabled mode.
"""

from .config import local_dev_settings
from .proxy import create_forwarding_app

__all__ = ["create_forwarding_app", "local_dev_settings"]
