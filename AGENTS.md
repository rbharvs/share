# AGENTS.md

## Project Context

This is a personal sharing service, built end-to-end and deployed on AWS + Cloudflare. Read `PRD.md` before changing anything substantial; it is the source of truth for product, security, architecture, API, infra, and testing decisions. `issues/` holds the vertical-slice breakdown the build followed and doubles as the deploy runbook.

## Core Architecture

- Backend: FastAPI on AWS Lambda via Mangum.
- Frontend: Vite + React + TypeScript + Tailwind + shadcn/ui, served by FastAPI after build.
- Infra: Pulumi TypeScript managing AWS + Cloudflare.
- Storage: DynamoDB metadata + separate private/public S3 buckets.
- Auth: Cloudflare Access for private hosts, plus app-level JWT verification.

## Required Host Boundaries

- `share.example.com`: private dashboard and mutation APIs only.
- `private.usercontent.example`: authenticated read-only rendered content only.
- `public.usercontent.example`: unauthenticated static public content only; should not hit Lambda.

Never serve arbitrary uploaded content from `share.example.com`. Never expose dashboard APIs from `private.usercontent.example`.

## Security Guardrails

- Uploaded HTML/JS is intentionally arbitrary and untrusted.
- Rendered content must use CSP sandbox without `allow-same-origin`.
- Do not add CORS for dashboard APIs.
- Dashboard POST APIs require CSRF header and Origin validation.
- Do not add local auth bypasses; local dev should use the Access-compatible JWT proxy model.
- SHA-256 URLs are not secrets; private content requires auth.

## Implementation Style

- Prefer deep, testable modules with small stable interfaces.
- Use dependency injection for repositories/services/auth so tests can override dependencies.
- Use Pydantic for API/domain models.
- Use domain exceptions mapped centrally to structured API errors.
- Test externally observable behavior, not implementation details.

## Testing Expectations

- Backend: pytest, FastAPI TestClient, moto for S3/DynamoDB integration-ish tests.
- Renderer: golden tests for HTML pass-through and Markdown unsafe/raw behavior.
- Frontend v1: typecheck and production build are sufficient.
- Infra: TypeScript typecheck plus focused config/unit checks where practical.

## Build/Deploy Expectations

- Use `uv` for backend Python dependencies.
- Use npm for frontend and infra.
- Build frontend, copy generated assets into backend package resources, then build one Lambda zip.
- Pulumi consumes the prebuilt artifact; avoid doing expensive build work inside Pulumi preview.
- Deployment is manual and gated: `make deploy` runs tests + build, then an interactive `pulumi up`. Run `make boundary-checks` after an apply.
- Stack config (`infra/Pulumi.prod.yaml`) is gitignored and holds account/zone ids + the KMS-encrypted Cloudflare token; copy `infra/Pulumi.prod.yaml.example` to start. Never commit real ids, tokens, or domains.
