# share backend

FastAPI application served on AWS Lambda via Mangum. See `../PRD.md` and
`../issues/` for the product, security, and architecture decisions.

Slice 01 lands the request spine: settings DI, the shared host registry, the
pure host/path/method gate, the structured error envelope (all PRD error
codes), the request-context + host-gate middleware, placeholder routes, and the
Mangum handler.

## Develop

```sh
uv sync --extra dev
uv run pytest
```
