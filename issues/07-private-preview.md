# [07] Private preview vertical: GET/HEAD /u/{sha} on the private content host

**Labels:** ready-for-dev
**User stories:** 17, 24, 26, 27
**Layers cut:** api, service, storage, auth, tests
**Est. production LOC:** ~160

## What to build

Authenticated read-only routes on `private.usercontent.example` that serve the private rendered artifact, plus the simple private root page and a disallow-all `robots.txt`. `GET /u/{sha}` streams the private artifact from S3; `HEAD /u/{sha}` returns the same headers with no body; missing SHA → `content_not_found`. Auth uses the **private-content audience**; the host gate permits only content `GET`/`HEAD` + root + robots (no mutation APIs reachable here).

**Exact rendered-content headers** (the CSP sandbox without `allow-same-origin` is the load-bearing defense isolating arbitrary uploaded JS from the dashboard origin):

```
Content-Type: text/html; charset=utf-8
Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-downloads
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cache-Control: no-store
X-Robots-Tag: noindex, nofollow
```

Build this header set behind a small shared helper — slice 13's public CloudFront response-headers policy must be byte-identical for the shared headers, and that is cross-checked there.

## Acceptance criteria

- [ ] Auth required; correct private audience required; dashboard audience rejected on the private host.
- [ ] `GET` returns the artifact with the exact CSP sandbox (no `allow-same-origin`) + `nosniff` + `no-referrer` + `no-store` + `noindex,nofollow` header set; `HEAD` returns equivalent metadata without a body.
- [ ] Missing SHA returns a structured `content_not_found` error.
- [ ] Private host serves only root/robots/content `GET`+`HEAD`; a dashboard API path on the private host → `route_not_allowed`; no mutation APIs reachable.

## Blocked by

- #02 — Cloudflare Access JWT verifier (private-content audience)
- #05 — Finalize upload (produces the private artifact this serves)
