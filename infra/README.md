# share infra

Pulumi TypeScript managing AWS + Cloudflare.

## Status

- **Slice 12 (done):** stateful data layer — DynamoDB single table + private and
  public S3 buckets. See `data.ts` (resources) and `config.ts` (naming, mirrored
  from the backend settings provider).
- **Slice 13:** compute + CDN (Lambda + API Gateway + CloudFront/OAC + ACM).
- **Slice 14:** Cloudflare DNS/Access + production deploy wiring.

## Layout

- `index.ts` — entrypoint: builds the data layer and exports the table/bucket
  identities slice 13 consumes. Also surfaces `lambdaArtifactPath`.
- `config.ts` — `DataConfig` + `loadDataConfig()`. Names (`share`,
  `share-private`, `share-public`) mirror `share.config.settings.Settings`, the
  single source of truth; any `share:*` Pulumi config key overrides per stack.
- `data.ts` — `createDataResources(cfg)`: the table + both buckets and their
  attached config (SSE, versioning-off, lifecycle, CORS, public-access block).
- `tests/data.spec.ts` — focused config checks run under Pulumi unit-test mocks
  (no AWS, no apply).

## Validate

```sh
npm run typecheck   # tsc --noEmit  (make infra-check)
npm test            # config checks under Pulumi mocks  (make infra-test)
```

Both run in CI. A real `pulumi preview` (operator step, needs the
`share-deploy` AWS profile) reports the create diff before any apply; the data
layer defaults to `us-east-1` even when `aws:region` is unset.

## Data-layer invariants (enforced + tested)

- One DynamoDB table: `pk`/`sk`, `PAY_PER_REQUEST`, point-in-time recovery on,
  TTL on `expires_at_epoch` (upload-session expiry).
- Two separate buckets, both default-SSE (AES256), neither versioned.
- Private bucket: `tmp/` expires after ~1 day; `raw/` and `artifacts/` never
  expire. CORS allows only the dashboard origin(s) and `POST`.
- Both buckets block all public access; the public bucket is reached only via
  CloudFront OAC (wired in slice 13).
