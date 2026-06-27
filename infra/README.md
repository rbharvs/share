# share infra

Pulumi TypeScript managing AWS + Cloudflare.

## Status

- **Slice 12 (done):** stateful data layer — DynamoDB single table + private and
  public S3 buckets. See `data.ts` (resources) and `config.ts` (naming, mirrored
  from the backend settings provider).
- **Slice 13 (done):** compute + CDN — the Mangum Lambda + regional API Gateway
  REST API (both private hosts) in `compute.ts`, and the public CloudFront/OAC
  distribution + ACM in `cdn.ts`.
- **Slice 14:** Cloudflare DNS/Access + production deploy wiring.

## Layout

- `index.ts` — entrypoint: builds data -> CDN -> compute and exports the
  identities slices 13/14 consume. Also surfaces `lambdaArtifactPath` (the
  prebuilt zip Pulumi treats as an opaque input — no build at preview).
- `config.ts` — `DataConfig`/`loadDataConfig()` + `EdgeConfig`/`loadEdgeConfig()`.
  Names/hosts (`share`, `share-private`, `share-public`, `share.example.com`,
  …) mirror `share.config.settings.Settings`, the single source of truth; any
  `share:*` Pulumi config key overrides per stack.
- `data.ts` — `createDataResources(cfg)`: the table + both buckets and their
  attached config (SSE, versioning-off, lifecycle, CORS, public-access block).
- `compute.ts` — `createComputeResources(...)`: the Lambda (py3.12/arm64/512 MB/
  30 s/Mangum, least-privilege IAM), the regional REST API with a Cloudflare-only
  resource policy + access logs, 30-day log retention, and regional custom
  domains + DNS-validated ACM certs for both private hosts.
- `cdn.ts` — `createCdnResources(...)`: the public CloudFront distribution
  (OAC-only origin, rendered-content response-headers policy, `/u/{sha}`
  slash/no-slash rewrite function, DNS-validated ACM cert) + the
  distribution-scoped bucket policy.
- `securityHeaders.ts` — TS mirror of `share.content.headers`; the public
  response-headers policy reproduces the shared headers byte-for-byte.
- `cloudflareIps.ts` — checked-in Cloudflare IPv4/IPv6 CIDR ranges.
- `tests/*.spec.ts` — focused config checks run under Pulumi unit-test mocks (no
  AWS, no apply), plus `securityHeaders.spec.ts` which cross-checks the TS
  headers against the Python source so they cannot drift.

## Validate

```sh
npm run typecheck   # tsc --noEmit  (make infra-check)
npm test            # config checks under Pulumi mocks  (make infra-test)
```

Both run in CI. A real `pulumi preview` (operator step, needs the
`share-deploy` AWS profile and the prebuilt `backend/dist/lambda.zip`) reports
the create diff before any apply; the stack defaults to `us-east-1` even when
`aws:region` is unset.

## Compute + CDN invariants (enforced + tested)

- Lambda: `python3.12` / `arm64` / 512 MB / 30 s, the `share.handler.handler`
  Mangum entrypoint, from the prebuilt zip (no in-Pulumi build). Least-privilege
  IAM scoped to its table, its two buckets, and `cloudfront:CreateInvalidation`
  on its own distribution.
- API Gateway: REGIONAL REST API + REGIONAL custom domains for both private
  hosts; a resource policy that DENIES any source IP outside the checked-in
  Cloudflare ranges; access logging on; Lambda + API logs retained 30 days.
- CloudFront: public host served via OAC only (bucket stays private, granted to
  this distribution alone); response-headers policy emits the rendered-content
  security headers (CSP `sandbox` without `allow-same-origin`, nosniff,
  no-referrer, noindex) + `Cache-Control: public, max-age=3600`, byte-matching
  the backend helper; a viewer-request function rewrites `/u/{sha}` and
  `/u/{sha}/` to `index.html` in place (no redirect). DNS-validated ACM cert.

## Data-layer invariants (enforced + tested)

- One DynamoDB table: `pk`/`sk`, `PAY_PER_REQUEST`, point-in-time recovery on,
  TTL on `expires_at_epoch` (upload-session expiry).
- Two separate buckets, both default-SSE (AES256), neither versioned.
- Private bucket: `tmp/` expires after ~1 day; `raw/` and `artifacts/` never
  expire. CORS allows only the dashboard origin(s) and `POST`.
- Both buckets block all public access; the public bucket is reached only via
  CloudFront OAC (wired in slice 13).
