# [13] Pulumi compute + CDN infrastructure: Lambda + API Gateway + CloudFront/OAC + ACM

**Labels:** ready-for-dev
**User stories:** 22, 27, 29, 33, 34, 35, 42
**Layers cut:** infra, service, tests
**Est. production LOC:** ~480 (interdependent edge stack; kept whole, near ceiling — justified)

## What to build

Pulumi TS for the AWS edge/compute layer, consuming the prebuilt zip from slice 11:

- **Lambda** — Python 3.12, ARM64, 512 MB, 30s timeout, Mangum handler (no in-Pulumi build).
- **API Gateway REST API v1** — regional custom domains for the two private hosts; a resource policy allowing only the checked-in Cloudflare IP ranges (defense in depth on top of Access + JWT); access logs enabled; Lambda/API log retention 30 days.
- **CloudFront** for `public.usercontent.example` via OAC to the (private) public bucket, with a response-headers policy and a rewrite function:
  - Response-headers policy emits the rendered-content security headers — `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-downloads` (NO `allow-same-origin`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: public, max-age=3600` — **byte-matching the slice-07 private header helper** for the shared headers.
  - Rewrite function maps `/u/{sha}` and `/u/{sha}/` to the object's `index.html` (no redirect needed); both URL shapes load.
- **ACM** certs, DNS-validated.
- The **real CloudFront invalidation client** replaces the slice-08 fake and computes the same slash/no-slash paths (needs the distribution ID created here).

Validated locally by `pulumi preview` + typecheck + config assertions; the deployed boundary curls run at the slice-14 manual apply.

## Acceptance criteria

- [ ] Lambda is py3.12 / arm64 / 512 MB / 30s with the Mangum handler, consuming the prebuilt zip (no in-Pulumi build).
- [ ] API Gateway REST v1 regional custom domains for both private hosts; resource policy limited to checked-in Cloudflare IP ranges; access logs on; 30-day retention.
- [ ] CloudFront serves the public host via OAC only; public bucket stays private; response-headers policy emits CSP sandbox (no `allow-same-origin`) + nosniff + no-referrer + `public, max-age=3600`, byte-matching the slice-07 private header helper where shared.
- [ ] CloudFront rewrite function maps `/u/{sha}` and `/u/{sha}/` to `index.html` (no redirect needed); both URL shapes load.
- [ ] ACM certs DNS-validated; the real CloudFront invalidation client replaces the slice-08 fake and computes the same slash/no-slash paths.

## Blocked by

- #12 — Pulumi data infrastructure (buckets + table to attach to)
- #08 — Publish/Unpublish (the `Invalidator` Protocol whose real client lands here)
