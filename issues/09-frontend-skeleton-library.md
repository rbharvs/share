# [09] Frontend skeleton + FastAPI static serving + local browser dev proxy + read-only library

**Labels:** ready-for-dev
**User stories:** 2, 14, 16, 17, 18, 30
**Layers cut:** frontend, api, infra, auth, tests
**Est. production LOC:** ~460 (kept whole — splitting shell/serving/proxy yields non-demoable half-UIs)

## What to build

The first real UI and the local-dev browsing experience, end to end.

A Vite + React + TS + Tailwind + shadcn/ui SPA shell served by FastAPI `StaticFiles` with SPA fallback ON the dashboard host only (API routes and `/assets` take precedence; `robots.txt` disallow) — this finalizes the host gate's SPA-fallback / asset / API-precedence path rules. First real view: the newest-first content library table (`fetch GET /api/content`, relative `/api/*` only) showing filename / type / size / status / timestamps, the always-present private link, and the public link only for published items, with structured error display.

This slice also lands the **local Access reverse-proxy forwarding** that slice 02 deferred: a Starlette/httpx reverse proxy mints a signed `Cf-Access-Jwt-Assertion` per request (verified by the same slice-02 path) and forwards `share.localhost:5174` → Vite (which proxies `/api/*` to FastAPI) and `private.localhost:5175` → FastAPI. `make dev` runs Vite + FastAPI + the local proxy together; `make preview` builds the SPA and serves it through FastAPI exactly as Lambda will (production-shape).

Notes:

- Host reads stay routed through `classify_host` (custom-domain `Host` vs `X-Forwarded-Host`). Confirm whether the SPA at `/` needs habit-tracker's trailing-slash `307` shim for relative asset URLs, and add it to the Mangum handler wrapper if so.
- Frontend stores no credentials/tokens in local/sessionStorage. Built assets are copied into backend package resources at build; generated assets are gitignored.

## Acceptance criteria

- [ ] SPA + `/assets` + robots served only on the dashboard host; API routes take precedence over SPA fallback; private/public hosts never serve the dashboard SPA.
- [ ] Library renders newest-first with filename/type/size/status/timestamps, a private link per item, and a public link only when published.
- [ ] Frontend uses only relative `/api/*` URLs and stores no credentials/tokens in local/sessionStorage.
- [ ] Local reverse-proxy forwards `share.localhost`→Vite and `private.localhost`→FastAPI, injecting a signed `Cf-Access-Jwt-Assertion` verified by the same slice-02 path.
- [ ] Frontend typecheck and production build pass; structured API errors are surfaced in the UI.
- [ ] `make dev` browsed at `http://share.localhost:5174` shows the authenticated library with real items; `make preview` serves the built SPA through FastAPI.
- [ ] Build copies built assets into backend package resources; generated assets are gitignored.

## Blocked by

- #06 — List content (the API this view consumes)
