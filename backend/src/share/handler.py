"""AWS Lambda entrypoint.

A thin Mangum wrapper around the same ASGI app used by TestClient and uvicorn,
so an API Gateway REST (v1) event exercises byte-identical code to local tests.
"""

from __future__ import annotations

from mangum import Mangum

from share.api import create_app

app = create_app()

#: Lambda handler — configure as ``share.handler.handler``.
handler = Mangum(app, lifespan="off")
