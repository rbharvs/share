# share

Personal serverless sharing service for uploading HTML/Markdown, privately previewing it, and optionally publishing it to a public URL.

Status: **built and deployed**. The full product (14 vertical slices) is implemented end-to-end and running on AWS + Cloudflare. See `PRD.md` for the implementation spec and `issues/` for the slice-by-slice breakdown.

## What it does

A private dashboard that can upload single-file HTML or Markdown documents, store them immutably by SHA-256 of the raw bytes, preview them privately, and publish them to a public URL. HTML is served as-is; Markdown is rendered to a minimal HTML shell. Uploaded content is treated as arbitrary and untrusted, so it is isolated on its own user-content domain and never shares an origin with the dashboard.

## Domain Model

```text
share.example.com
  Private dashboard and mutation APIs.

private.usercontent.example
  Private authenticated rendered content.

public.usercontent.example
  Public static rendered content (served by the CDN, never hits Lambda).
```

Rendered content is isolated on `usercontent.example` because uploaded HTML/JS is intentionally arbitrary and untrusted.

## Architecture

```text
Cloudflare Access
  -> API Gateway REST API
  -> Lambda / FastAPI / Mangum
  -> DynamoDB metadata
  -> S3 private source/artifacts
  -> S3 public artifacts + CloudFront
```

Infrastructure is managed with Pulumi TypeScript (AWS + Cloudflare).

## Stack

- Backend: FastAPI, Mangum, Pydantic, boto3, `uv`
- Frontend: Vite, React, TypeScript, Tailwind, shadcn/ui (served by FastAPI after build)
- Infra: Pulumi TypeScript, AWS, Cloudflare
- Storage: DynamoDB + separate private/public S3 buckets
- Auth: Cloudflare Access + app-level JWT verification
- Markdown rendering: `wenmode`

## Layout

```text
backend/   FastAPI app, domain modules, renderer, tests (pytest + moto)
frontend/  Vite + React dashboard
infra/     Pulumi TypeScript (AWS + Cloudflare), config + unit checks
scripts/   boundary checks and operational helpers
issues/    the vertical-slice breakdown the build followed
```

## Working with it

Backend deps use `uv`; frontend and infra use npm. Common tasks run from the root Makefile:

```bash
make dev      # FastAPI + Vite + the local Access proxy together
make preview  # build the SPA and serve it through FastAPI, production-shape
make check    # lint + typecheck backend, frontend, and infra
make test     # backend (pytest + moto) and infra test suites
make fix      # auto-fix lint + format
```

Slices 01–11 run entirely locally on `moto` + a local Cloudflare-Access-compatible JWT proxy — no cloud needed. Only the infra slices (12–14) touch real AWS/Cloudflare.

## Deploy

Deployment is manual and gated. `make deploy` runs the tests + build, then an interactive `pulumi up` whose yes/no prompt is the gate. After an apply, `make boundary-checks` exercises the host boundaries (Access-gated dashboard/private hosts, public host served only by the CDN, raw API Gateway invoke rejected).

Stack configuration lives in `infra/Pulumi.prod.yaml` (gitignored — it holds account/zone ids and the KMS-encrypted Cloudflare token); copy `infra/Pulumi.prod.yaml.example` to start. Hosts, owner email, bucket names, and team slug are all config-driven, so the same code deploys to any account/domain. See `issues/README.md` for the full deploy runbook and prerequisites.

## Key Constraints

- V1 supports single-file HTML/Markdown only.
- Uploads are limited to 5 MB.
- Content is immutable and addressed by SHA-256 of raw uploaded bytes.
- HTML uploads are served as-is.
- Markdown is rendered to a minimal HTML shell.
- No delete, slugs, bundles, metadata extraction, or OG images in v1.

## Security Notes

- SHA-256 URLs are not secrets.
- Private content requires Cloudflare Access and app-level JWT verification.
- Never serve uploaded content from `share.example.com`.
- Never expose dashboard APIs from `private.usercontent.example`.
- Rendered content uses a CSP sandbox without `allow-same-origin`.

## Repo Notes

Read these first:

- `PRD.md` — full product/architecture/testing spec
- `AGENTS.md` — coding-agent implementation guidance
