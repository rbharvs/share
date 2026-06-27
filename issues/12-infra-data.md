# [12] Pulumi data infrastructure: DynamoDB single table + two S3 buckets

**Labels:** ready-for-dev
**User stories:** 36, 37, 42
**Layers cut:** infra, schema/data, storage, tests
**Est. production LOC:** ~350

## What to build

Pulumi TypeScript for the stateful AWS layer in `us-east-1` (the first real-cloud slice; validated by `pulumi preview` + typecheck + focused config assertions, no apply required):

- The single DynamoDB metadata table (pk/sk, `PAY_PER_REQUEST`, PITR enabled, TTL attribute for upload-session expiry).
- A private S3 bucket and a separate public S3 bucket, both with default SSE and no versioning.
- `tmp/` lifecycle expiration (~1 day) on the private bucket; `raw/` and `artifacts/` do not expire.
- Private-bucket CORS allowing only the dashboard origin(s) and `POST` (for the presigned upload).
- The public bucket kept private (public access blocked) and configured for CloudFront-OAC-only access (OAC + distribution wired in slice 13).

Bucket/table naming must match the slice-04/05 ObjectStorage + MetadataRepository config — the settings provider (slice 01) is the single source of truth.

## Acceptance criteria

- [ ] DynamoDB single table with PITR enabled and a TTL attribute for upload-session expiry.
- [ ] Private and public S3 buckets are separate; both use default encryption; neither uses versioning.
- [ ] `tmp/` lifecycle expiration (~1 day) exists on the private bucket; `raw/` and `artifacts/` do not expire.
- [ ] Public bucket is private (public access blocked), ready for CloudFront OAC.
- [ ] Private-bucket CORS allows only the dashboard origin(s) and `POST`.
- [ ] Infra config checks + `pulumi preview` + TS typecheck pass in CI.

## Blocked by

- #11 — Packaging, build pipeline, and CI (Pulumi workspace scaffold)
