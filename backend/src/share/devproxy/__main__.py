"""Run the local Access reverse proxy: ``python -m share.devproxy``.

Starts two listeners on the browser-facing local origins, sharing one signing
key (one JWKS verifies both audiences):

* ``share.localhost:5174`` -> dashboard upstream (Vite by default; FastAPI under
  ``make preview``), minting dashboard-audience tokens.
* ``private.localhost:5175`` -> FastAPI, minting private-audience tokens.

``make dev`` runs this alongside Vite and FastAPI; ``make preview`` points the
dashboard upstream at FastAPI so the built SPA is served production-shape. The
dashboard upstream is overridable via ``SHARE_DASHBOARD_UPSTREAM``.
"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from share.auth import LocalAccessSigner
from share.config import Settings

from .config import (
    DASHBOARD_HOST,
    DASHBOARD_PROXY_PORT,
    FASTAPI_URL,
    LOCAL_DASHBOARD_AUDIENCE,
    LOCAL_ISSUER,
    LOCAL_PRIVATE_AUDIENCE,
    PRIVATE_HOST,
    PRIVATE_PROXY_PORT,
    VITE_DEV_URL,
)
from .proxy import create_forwarding_app


def _build_signer() -> LocalAccessSigner:
    # One key for both listeners so a single JWKS verifies both audiences.
    return LocalAccessSigner(
        issuer=LOCAL_ISSUER,
        audience=LOCAL_DASHBOARD_AUDIENCE,
        allowed_email=Settings().allowed_owner_email,
    )


async def _run() -> None:
    signer = _build_signer()
    dashboard_upstream = os.environ.get("SHARE_DASHBOARD_UPSTREAM", VITE_DEV_URL)

    dashboard_app = create_forwarding_app(
        signer=signer,
        audience=LOCAL_DASHBOARD_AUDIENCE,
        upstream=dashboard_upstream,
        forward_host=DASHBOARD_HOST,
    )
    private_app = create_forwarding_app(
        signer=signer,
        audience=LOCAL_PRIVATE_AUDIENCE,
        upstream=FASTAPI_URL,
        forward_host=PRIVATE_HOST,
    )

    servers = [
        uvicorn.Server(
            uvicorn.Config(
                dashboard_app,
                host="127.0.0.1",
                port=DASHBOARD_PROXY_PORT,
                log_level="info",
            )
        ),
        uvicorn.Server(
            uvicorn.Config(
                private_app,
                host="127.0.0.1",
                port=PRIVATE_PROXY_PORT,
                log_level="info",
            )
        ),
    ]
    print(
        f"local Access proxy: http://{DASHBOARD_HOST} -> {dashboard_upstream} | "
        f"http://{PRIVATE_HOST} -> {FASTAPI_URL}"
    )
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
