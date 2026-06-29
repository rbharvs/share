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

## Tooling

- `mise` pins all dev tool versions (node 24, python 3.13, uv, Pulumi CLI, hk, oxlint, oxfmt) in `mise.toml` + `mise.lock`, and is the task runner. There is no Makefile. Run `mise tasks` to list tasks; common ones: `mise run dev | preview | check | test | fix | build | deploy | boundary-checks`.
- First-time setup: `mise install`, `mise trust`, then `hk install --mise` for git hooks.
- Lint/format: `ruff` for Python (in the backend `uv` dev group — do NOT add ruff to mise), `oxlint` + `oxfmt` for frontend + infra TS/JS only (configs `.oxlintrc.json` / `.oxfmtrc.json`). `oxfmt` is deliberately scoped to TS/JS so it never reformats Pulumi YAML / JSON / the example config.
- hk runs a single comprehensive pre-commit hook (no pre-push): auto-fixers + typechecks + all three test suites (backend pytest, frontend vitest, infra mocha). Each step only fires when a file under its workspace is staged. CI re-runs the same checks.
- Dependency pin policy: newest release >= 72h old (`min-release-age=3` in each `.npmrc`; `mise run relock` with `--exclude-newer '3 days'` for Python; Renovate enforces going forward). `wenmode` and `syrupy` are documented exceptions — keep their exact pins; do not let `mise run relock` drop them.
- `UV_FROZEN=1` (set in `mise.toml`) makes backend installs use `uv.lock` exactly; update the lock only via `mise run relock`.

## Build/Deploy Expectations

- Use `uv` for backend Python dependencies; npm for frontend and infra.
- Build frontend, copy generated assets into backend package resources, then build one Lambda zip.
- Pulumi consumes the prebuilt artifact; avoid doing expensive build work inside Pulumi preview.
- The dev/build host runs python 3.13, but the deployed Lambda runtime stays `python3.12` — `scripts/build_lambda.py` cross-targets 3.12/arm64 explicitly. Do not bump the Lambda runtime here; that is a separate deploy-gated change.
- Deployment is manual and gated: `mise run deploy` runs tests + build, then an interactive `pulumi up`. Run `mise run boundary-checks` after an apply. Deploy is never referenced from CI.
- The Pulumi CLI is mise-managed and pinned to the version that created the stack state. The first deploy after the `@pulumi/aws` v7 bump must be `pulumi up --refresh --run-program` (one-time, non-destructive `region`-field state migration).
- Stack config (`infra/Pulumi.prod.yaml`) is gitignored and holds account/zone ids + the KMS-encrypted Cloudflare token; copy `infra/Pulumi.prod.yaml.example` to start. Never commit real ids, tokens, or domains — and keep `mise.toml` / `hk.pkl` free of secrets, ids, and real hostnames.
