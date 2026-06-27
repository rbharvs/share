# [14] Pulumi Cloudflare infra + production deploy wiring

**Labels:** ready-for-dev
**User stories:** 1, 42
**Layers cut:** infra, auth, tests
**Est. production LOC:** ~250

## What to build

Pulumi TS for Cloudflare, plus the manual deploy runbook — the chokepoint that joins infra and app auth config and the first full exercise of the live ingress chain.

- **DNS** — private host records proxied to API Gateway; public host DNS-only to CloudFront.
- **Access** — two separate applications/policies (dashboard audience + private-content audience), 7-day session, allowed owner email configured plainly (not a secret).
- **AccessConfig mirroring** — the production issuer/audiences are mirrored into the backend `AccessConfig` (slice 02) so the verifier accepts real Cloudflare tokens per host. The per-host AUD is the cross-host replay defense; it originates in Cloudflare/Pulumi and must be mirrored out-of-band — drift breaks auth (verifier fails closed). Pin down the single source of truth and how the app reads per-host audiences.
- **Manual deploy** — document/wire the runbook: run tests + build, then the single gated manual `pulumi up`. No automated CI deploy.

This is where the **deployed-boundary checks** (grafted from the deploy-first plan) are actually exercised post-apply.

## Acceptance criteria

- [ ] Private host DNS proxied; public host DNS-only to CloudFront.
- [ ] Separate Access applications for dashboard and private content with distinct audiences, 7-day session, allowed owner email (plain config).
- [ ] Production `AccessConfig` audiences/issuer mirror the Cloudflare apps (per-host AUD cross-host replay defense); local issuer/audience never deployed.
- [ ] Deploy is manual via `pulumi up` and runs tests + build first; no automated CI deploy.
- [ ] Post-deploy boundary checks pass: Access-gated route returns 200; a raw API Gateway invoke from a non-Cloudflare IP → 403; `public.usercontent.example` reaching Lambda → 403; both `/u/{sha}` and `/u/{sha}/` load unauthenticated.

## Blocked by

- #13 — Pulumi compute + CDN infrastructure (the API Gateway + CloudFront to point DNS at)
- #02 — Cloudflare Access JWT verifier (the `AccessConfig` the audiences mirror into)
