"""Local FastAPI dev server app: ``uvicorn share.dev_app:app``.

The same :func:`share.api.create_app`, but built from the local dev settings
(local hosts + local Access issuer/audiences + the proxy's JWKS URL) and the
package-bundled SPA. Used by ``mise run dev`` (behind Vite + the local proxy) and by
``mise run preview`` (serving the built SPA production-shape). Production uses
:mod:`share.handler` instead, with the real Cloudflare config.
"""

from __future__ import annotations

from share.api import create_app
from share.devproxy.config import local_dev_settings

app = create_app(local_dev_settings())
