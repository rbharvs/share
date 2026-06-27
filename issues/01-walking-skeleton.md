# [01] Walking skeleton: app + host gate + error mapper + request/logging middleware + Mangum handler

**Labels:** ready-for-dev
**User stories:** 23, 26, 30, 31, 32
**Layers cut:** api, service, infra, tests
**Est. production LOC:** ~470 (irreducible skeleton; stays whole)

## What to build

The end-to-end request spine that every later slice plugs into, with no content or auth yet. A FastAPI app takes any request, assigns a `request_id` and emits one structured JSON log line, classifies the raw `Host` header to a host-kind via a shared registry, runs a pure host/path/method gate, and either dispatches to a trivial placeholder route or returns the structured error envelope. The same ASGI app is wrapped by a thin Mangum handler so `TestClient`, `uvicorn`, and a raw API Gateway REST v1 event dict all exercise identical code.

This slice also lands the cross-cutting **prefactoring** the rest of the project depends on: the monorepo scaffold (backend `uv` project `src/share/` with deep modules per subpackage mirroring habit-tracker's Protocol + impl + re-exporting `__init__.py` convention; Vite frontend workspace; Pulumi-TS infra workspace; root Makefile with `fix`/`check`/`format`/`test`/`dev` targets), the shared host registry, the error envelope + all error codes, and the settings/config DI provider.

Key decisions (encode now):

- **Shared host registry** — one `classify_host(raw_host) -> HostKind` keyed by exact strings (`share.example.com`, `private.usercontent.example`, `public.usercontent.example`, plus `share.localhost:5174` / `private.localhost:5175` dev equivalents). Routes never read the `Host` header directly — one adapter for any future `X-Forwarded-Host`/CloudFront ingress change.
- **Host/path/method gate** (pure, zero FastAPI imports):

  | Host kind | Allowed |
  | --- | --- |
  | dashboard | SPA/assets/robots + `/api/*` |
  | private-content | root, robots, `GET`/`HEAD /u/{sha}` only — dashboard APIs → `route_not_allowed` |
  | public-content | always `403 host_not_allowed` (must never reach Lambda) |
  | unknown | `403 host_not_allowed` |

- **Single error primitive** — `error_response(exc, request_id) -> JSONResponse` shared by BOTH the FastAPI exception handlers AND the gate middleware (the middleware sits outside the handler stack and must map inline). All ~15 PRD error codes exist up front as `ShareError` subclasses carrying `code` + `status_code`: `auth_required, auth_invalid, host_not_allowed, route_not_allowed, validation_error, upload_not_found, upload_expired, upload_not_uploaded, upload_too_large, unsupported_source_type, invalid_utf8, content_not_found, publish_failed, unpublish_failed, storage_error`. Envelope shape: `{"error": {"code", "message", "request_id"}}`.
- **Middleware order is load-bearing** — `RequestContext` is OUTERMOST (added last) so gate-rejection 403s still carry `request_id` + `X-Request-Id`; `HostGate` is inner. `BaseHTTPMiddleware`-raised `ShareError`s are not caught by FastAPI exception handlers, so the gate maps via `error_response` inline.
- **Settings/config DI** — env-driven hosts, allowed owner email, per-host issuer/audience/jwks_url placeholders, table name, two bucket names, region. Prod and local config sets are swappable and never co-deployed; there is no `APP_ENV` auth bypass — only the injected config differs.

## Acceptance criteria

- [ ] Pure `host_gate.evaluate(host, path, method)` returns a `HostKind` or raises `ShareError` with zero FastAPI imports; covered by string-only unit tests.
- [ ] Dashboard host allows SPA/assets/API/robots placeholders; private host allows root/robots/content `GET`+`HEAD` only and rejects dashboard APIs with `route_not_allowed`; public and unknown hosts return `403 host_not_allowed`.
- [ ] No `DELETE` route exists; unknown routes return `route_not_allowed` (story 23 by-absence guard test).
- [ ] Every response carries `X-Request-Id`; gate-rejection 403s still carry `request_id` and `X-Request-Id` (RequestContext outer, HostGate inner).
- [ ] `error_response(exc, request_id)` is a single standalone primitive used by BOTH the FastAPI exception handlers AND the gate middleware; all ~15 PRD error codes exist as `ShareError` subclasses with `code` + `status_code`.
- [ ] One structured JSON log line per request with `request_id`, host, path, method.
- [ ] `uv run pytest` green: pure gate string-table tests + `TestClient(raise_server_exceptions=False)` per host class + a raw API Gateway REST v1 event dict invoked through the Mangum handler (dashboard `/` → 200; private API → 403 `route_not_allowed`; public/unknown → 403).

## Blocked by

None - can start immediately.
