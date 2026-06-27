# share

Personal serverless sharing service for uploading HTML/Markdown, privately previewing it, and optionally publishing it to a public URL.

Status: **greenfield / design complete**. See `PRD.md` for the full implementation spec.

## Goal

Build a private dashboard at:

```text
share.example.com
```

that can upload single-file HTML or Markdown documents, store them immutably by SHA-256, preview them privately, and publish them publicly.

## Domain Model

```text
share.example.com
  Private dashboard and mutation APIs.

private.usercontent.example
  Private authenticated rendered content.

public.usercontent.example
  Public static rendered content.
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

Infrastructure will be managed with Pulumi TypeScript.

## Planned Stack

- Backend: FastAPI, Mangum, Pydantic, boto3, `uv`
- Frontend: Vite, React, TypeScript, Tailwind, shadcn/ui
- Infra: Pulumi TypeScript, AWS, Cloudflare
- Storage: DynamoDB + separate private/public S3 buckets
- Auth: Cloudflare Access + app-level JWT verification
- Markdown rendering: `wenmode`

## Key Constraints

- V1 supports single-file HTML/Markdown only.
- Uploads are limited to 5 MB.
- Content is immutable and addressed by SHA-256 of raw uploaded bytes.
- HTML uploads are served as-is.
- Markdown is rendered to a minimal HTML shell.
- No delete, slugs, bundles, metadata extraction, or OG images in v1.

## Security Notes

- SHA-256 URLs are not secrets.
- Private content must require Cloudflare Access and app-level JWT verification.
- Never serve uploaded content from `share.example.com`.
- Never expose dashboard APIs from `private.usercontent.example`.
- Rendered content must use a CSP sandbox without `allow-same-origin`.

## Repo Notes

Read these first:

- `PRD.md` — full product/architecture/testing spec
- `AGENTS.md` — coding-agent implementation guidance
