"""Real-HTTP roundtrip: ``LocalAccessSigner`` mints a token and serves its JWKS
over a live socket; the production ``CachingJwksProvider`` (urllib transport)
fetches it and the verifier accepts the token through the identical code path.
"""

from __future__ import annotations

import http.server
import json
import threading
from contextlib import contextmanager

from conftest import DASHBOARD_AUDIENCE, ISSUER, OWNER_EMAIL
from share.auth import (
    AccessConfig,
    AccessVerifier,
    CachingJwksProvider,
    LocalAccessSigner,
    urllib_fetch,
)
from share.hosts import HostKind


@contextmanager
def _serve_jwks(jwks: dict):
    body = json.dumps(jwks).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence test server logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/cdn-cgi/access/certs"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_local_signer_token_accepted_over_real_http():
    signer = LocalAccessSigner(
        issuer=ISSUER, audience=DASHBOARD_AUDIENCE, allowed_email=OWNER_EMAIL
    )

    with _serve_jwks(signer.jwks()) as jwks_url:
        configs = {
            HostKind.DASHBOARD: AccessConfig(
                issuer=ISSUER,
                audience=DASHBOARD_AUDIENCE,
                jwks_url=jwks_url,
                allowed_email=OWNER_EMAIL,
            )
        }
        verifier = AccessVerifier(
            configs, CachingJwksProvider(fetch=urllib_fetch)
        )

        token = signer.sign()  # fresh, Cloudflare-shaped token
        principal = verifier.verify(token, HostKind.DASHBOARD)

        assert principal.email == OWNER_EMAIL
        assert principal.host is HostKind.DASHBOARD

        # A second token verifies from the JWKS cache — no second fetch needed.
        token2 = signer.sign()
        assert verifier.verify(token2, HostKind.DASHBOARD).email == OWNER_EMAIL
