# PRD: Private Share Dashboard and Isolated User-Content Hosting

## Document Purpose

This PRD is intended to be self-contained. It captures the product, security, architecture, API, infrastructure, local-development, and testing decisions for the first version of a personal sharing service. The developer implementing this should not need prior conversation context.

The repository is currently greenfield. This document defines the v1 target state.

## Executive Summary

Build a personal serverless sharing service with:

- A private dashboard at `share.example.com` for uploading and managing shared documents.
- A private authenticated content host at `private.usercontent.example` for previewing unpublished rendered content.
- A public static content host at `public.usercontent.example` for published content.

The service supports uploading one UTF-8 HTML or Markdown file at a time. Uploads are private by default. Each finalized upload is immutable and identified by the SHA-256 hash of the raw uploaded bytes. The owner can publish or unpublish an item. Published items are served publicly at:

```text
https://public.usercontent.example/u/{sha256}
```

Private previews are served at:

```text
https://private.usercontent.example/u/{sha256}
```

Arbitrary HTML and JavaScript are intentionally allowed. Because of that, rendered content must never share an origin with the private dashboard. The separate `usercontent.example` domain and CSP sandbox headers are core security requirements, not optional polish.

The backend follows the same broad architecture as a [sibling FastAPI-on-Lambda project](https://github.com/rbharvs/habit-tracker): FastAPI on AWS Lambda through Mangum, API Gateway REST API, DynamoDB, S3, and Cloudflare Access at ingress. Infrastructure is managed with Pulumi TypeScript instead of SAM.

## Goals

1. Provide a private dashboard where the owner can upload HTML or Markdown.
2. Store uploads immutably and address them by SHA-256.
3. Provide authenticated private previews of uploaded content.
4. Allow the owner to publish and unpublish content.
5. Serve public content cheaply and statically through CloudFront and S3.
6. Allow arbitrary uploaded HTML and JavaScript while isolating it from admin functionality.
7. Use Cloudflare Access for private authentication, with AWS/app-layer defense in depth.
8. Use Pulumi to manage AWS and Cloudflare infrastructure.
9. Keep v1 small, testable, and suitable for a personal low-traffic tool.

## Non-Goals for v1

1. Multi-file bundles or zip uploads.
2. Mutable documents or editing uploaded content.
3. Slugs, aliases, vanity URLs, or short links.
4. Delete/soft-delete workflows.
5. Multi-user workspaces.
6. Sharing private preview links with anyone beyond the owner allowlist.
7. Metadata extraction from uploaded content.
8. Open Graph metadata injection or screenshot generation.
9. Malware scanning or external-resource scanning.
10. Moving private previews to CloudFront/Lambda@Edge.
11. Automated production deploys from CI.
12. Uploads larger than 5 MB.

## Glossary

- **Dashboard**: The private management UI at `share.example.com`.
- **Content item**: One finalized uploaded HTML or Markdown file, identified by SHA-256.
- **Source**: The exact uploaded UTF-8 bytes stored immutably in private S3.
- **Artifact**: Rendered HTML produced from the source and served to browsers.
- **Private artifact**: Rendered artifact stored in private S3 and served through the authenticated private content host.
- **Public artifact**: Rendered artifact stored in public S3 and served through CloudFront.
- **Private content host**: `private.usercontent.example`, authenticated and read-only.
- **Public content host**: `public.usercontent.example`, unauthenticated static hosting.
- **Upload session**: Temporary DynamoDB record created before direct S3 upload and consumed by finalize.
- **Finalize**: Server-side process that validates a temporary upload, computes SHA-256, stores canonical source, generates private artifact, and writes metadata.
- **Publish**: Process that generates/writes the public artifact and marks metadata as published.
- **Unpublish**: Process that deletes public artifact, invalidates CloudFront paths, and marks metadata as unpublished.
- **Workspace**: The single v1 personal library, internally represented as the default workspace/user.

## High-Level Architecture

```text
Private dashboard flow:

Browser
  -> Cloudflare Access
  -> Cloudflare proxied DNS: share.example.com
  -> API Gateway REST API, restricted to Cloudflare IP ranges
  -> Lambda FastAPI app through Mangum
  -> DynamoDB metadata + private S3 + public S3 + CloudFront invalidation

Private content flow:

Browser
  -> Cloudflare Access
  -> Cloudflare proxied DNS: private.usercontent.example
  -> same API Gateway REST API
  -> same Lambda FastAPI app through Mangum
  -> private S3 artifact

Public content flow:

Browser
  -> DNS-only public.usercontent.example
  -> CloudFront
  -> private S3 origin through Origin Access Control
```

There is one FastAPI Lambda for the dashboard and private content host. It must use host-based route gating so dashboard mutation APIs are available only from `share.example.com`, while `private.usercontent.example` remains read-only.

`public.usercontent.example` should never route to Lambda. If it accidentally does, the app must return 403.

## Domains and Routing

### Production hostnames

| Host | Purpose | Auth | Origin | Notes |
| --- | --- | --- | --- | --- |
| `share.example.com` | Private dashboard and JSON API | Cloudflare Access | API Gateway -> Lambda | Only host with mutation APIs |
| `private.usercontent.example` | Private rendered content | Cloudflare Access | API Gateway -> Lambda | Read-only content host |
| `public.usercontent.example` | Public rendered content | None | CloudFront -> S3 | Static public host |

### Dashboard routes

```text
GET  /                         Serve Vite SPA dashboard
GET  /assets/*                 Serve built Vite assets
GET  /robots.txt               Disallow crawling
GET  /api/content              List content items
POST /api/uploads/presign      Create presigned S3 POST upload session
POST /api/uploads/finalize     Finalize temporary S3 upload
POST /api/content/{sha}/publish
POST /api/content/{sha}/unpublish
```

Dashboard SPA fallback is enabled for browser-navigation paths. API routes take precedence over the frontend fallback.

### Private content routes

```text
GET  /                         Simple authenticated "private content host" page
GET  /robots.txt               Disallow crawling
GET  /u/{sha256}               Serve private rendered artifact
HEAD /u/{sha256}               Metadata-only equivalent of private artifact route
```

No dashboard APIs are available from the private content host.

### Public content routes

```text
GET /                          Simple static public content host page
GET /robots.txt                Allow crawling
GET /u/{sha256}                Serve public rendered artifact
GET /u/{sha256}/               Serve same artifact, no redirect required
```

CloudFront rewrites `/u/{sha256}` and `/u/{sha256}/` to the S3 object for the item's `index.html` artifact. The canonical URL shown in the dashboard omits the trailing slash.

## Content Lifecycle

The content lifecycle is intentionally small:

```text
uploaded      # private only; private artifact exists
published     # private artifact exists and public artifact exists
unpublished   # private artifact exists; public artifact was removed
```

Allowed transitions:

```text
uploaded    -> published
published   -> unpublished
unpublished -> published
```

Required lifecycle semantics:

- Finalized uploads start as `uploaded` unless deduplicated to an existing item.
- Publish is idempotent.
- Unpublish is idempotent.
- Republish uses the same public URL.
- No delete operation exists in v1.
- SHA-256 is not a secret. Private access depends on authentication, not URL obscurity.

## Upload and Finalize Flow

The dashboard uploads directly to S3 using presigned POST. The server does not accept large upload bodies.

```text
1. Browser selects or drops a file.
2. Dashboard infers source type from filename/MIME and allows user override.
3. Dashboard calls POST /api/uploads/presign.
4. Backend creates an upload session and returns a presigned S3 POST.
5. Browser uploads file directly to private S3 using XHR to show progress.
6. Dashboard calls POST /api/uploads/finalize with the upload ID.
7. Backend validates upload session and temporary object.
8. Backend reads temporary object, validates UTF-8, computes SHA-256 over raw bytes.
9. Backend stores canonical raw source if it is new.
10. Backend generates private artifact.
11. Backend writes/updates metadata in DynamoDB.
12. Backend deletes the temporary object.
13. Backend returns the content item representation.
```

### Upload constraints

- Maximum upload size: 5 MB.
- Supported source types: `html`, `markdown`.
- Supported file model: one text file only.
- All uploaded bytes must decode as UTF-8.
- SHA-256 is computed over raw uploaded bytes before any decoding normalization.
- Presigned POST policy must enforce the size limit and temporary key prefix.
- Temporary S3 objects expire after approximately one day.
- Upload session records expire after approximately one hour through DynamoDB TTL.

### Source type behavior

| Source type | Accepted examples | Canonical raw key suffix | Artifact behavior |
| --- | --- | --- | --- |
| `html` | `.html`, `.htm`, explicit override | `source.html` | Copy raw bytes exactly |
| `markdown` | `.md`, `.markdown`, `.txt` with override | `source.md` | Render with `wenmode` into HTML shell |

The original filename is preserved in metadata, but canonical raw object names use stable source filenames by type.

## Publish and Unpublish Flow

### Publish

Publishing generates a public artifact from the canonical raw source and writes it to the public bucket.

Requirements:

- Publishing must be idempotent.
- If metadata says `published` and public object exists, return success.
- If metadata says `published` but public object is missing, regenerate it.
- If public object exists but metadata is not `published`, reconcile by updating metadata after ensuring the object is correct.
- Public artifact generation reads canonical raw source, not the private preview artifact.
- Publish returns the updated content item representation.

### Unpublish

Unpublishing removes the public artifact and invalidates CloudFront paths.

Requirements:

- Unpublishing must be idempotent.
- Delete the public object if present.
- Invalidate both slash and no-slash CloudFront paths for the item.
- Mark metadata as `unpublished`.
- Return the updated content item representation.

## Rendering Requirements

### HTML uploads

- Allow arbitrary HTML and JavaScript.
- Do not sanitize.
- Do not wrap.
- Do not inject title, metadata, scripts, or styles.
- Preserve exact raw bytes for artifacts after UTF-8 validation.

### Markdown uploads

- Use `wenmode` behind a small renderer adapter.
- Configure rendering to preserve raw HTML and not sanitize URLs.
- Render to a full HTML document.
- Include a minimal self-contained CSS shell.
- Use the original filename as the document title.
- Preserve unsafe/raw behaviors intentionally, including raw HTML and JavaScript URLs.

### Rendered content headers

All private and public rendered artifacts use:

```text
Content-Type: text/html; charset=utf-8
Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-downloads;
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

Important CSP requirement: do not include `allow-same-origin`.

Private rendered artifacts additionally use:

```text
Cache-Control: no-store
X-Robots-Tag: noindex, nofollow
```

Public rendered artifacts use approximately:

```text
Cache-Control: public, max-age=3600
```

Public content is indexable by default.

## Data Model

Use DynamoDB as the source of truth for metadata. Do not rely on S3 object metadata or tags as queryable application state.

### Workspace model

V1 has one personal workspace:

```text
USER#default
```

The app still stores `created_by` from the verified Cloudflare Access email for audit/debugging.

### Content metadata fields

Each content item stores at least:

```text
sha256
source_type: html | markdown
original_filename
size_bytes
status: uploaded | published | unpublished
created_at
updated_at
published_at
created_by
raw_key
private_artifact_key
public_key
last_upload_id
```

`public_key` is null or absent when not published.

### DynamoDB single-table shape

Use a two-item pattern for each content item:

```text
Lookup item:
  pk = CONTENT#{sha256}
  sk = META

List item:
  pk = USER#default
  sk = CONTENT#{created_at}#{sha256}
```

The lookup item supports direct access by SHA. The list item supports newest-first dashboard listing without scanning. The duplicated metadata must be kept consistent on finalize, publish, and unpublish.

Upload sessions are also stored in DynamoDB:

```text
Upload session item:
  pk = UPLOAD#{upload_id}
  sk = META
```

Upload session fields include:

```text
upload_id
created_by
original_filename
source_type
tmp_key
max_size_bytes
created_at
expires_at_epoch
```

## Object Storage Layout

Use two S3 buckets: one private bucket and one public bucket.

### Private bucket

```text
tmp/{upload_id}
raw/{sha256}/source.html
raw/{sha256}/source.md
artifacts/{sha256}/index.html
```

- `tmp/` stores temporary presigned uploads.
- `raw/` stores immutable canonical source.
- `artifacts/` stores authenticated private rendered artifacts.
- Only `tmp/` has lifecycle expiration.
- Private raw source and private artifacts do not expire in v1.

### Public bucket

```text
u/{sha256}/index.html
robots.txt
index.html
```

- `u/{sha256}/index.html` is created on publish and deleted on unpublish.
- Public root and robots files are static support files.
- The bucket is private and accessible to CloudFront only through Origin Access Control.

### S3 encryption/versioning/lifecycle

- Use default S3 server-side encryption.
- Do not enable S3 versioning in v1.
- Do not enforce total storage quota in v1.
- Expire abandoned `tmp/` objects after about one day.

## API Contracts

### Common content item response

Finalize, list, publish, and unpublish all use the same content item representation:

```json
{
  "sha256": "full-sha256",
  "short_sha": "first-12ish-chars",
  "source_type": "html",
  "original_filename": "demo.html",
  "size_bytes": 12345,
  "status": "published",
  "created_at": "2026-06-24T17:52:35Z",
  "updated_at": "2026-06-24T17:53:35Z",
  "published_at": "2026-06-24T17:53:35Z",
  "private_url": "https://private.usercontent.example/u/full-sha256",
  "public_url": "https://public.usercontent.example/u/full-sha256"
}
```

`public_url` is null when the item is not published.

### Presign upload

Request:

```json
{
  "filename": "demo.html",
  "content_type": "text/html",
  "source_type": "html"
}
```

Response:

```json
{
  "upload_id": "uuid-v4",
  "url": "https://private-bucket.s3.us-east-1.amazonaws.com/",
  "fields": {
    "key": "tmp/{upload_id}"
  },
  "max_size_bytes": 5242880
}
```

The exact returned S3 fields depend on boto3's presigned POST output.

### Finalize upload

Request:

```json
{
  "upload_id": "uuid-v4"
}
```

Response: common content item response.

Finalize must use the stored upload session for filename/source type. It must not trust new filename/source type values from the finalize request.

### List content

Request:

```text
GET /api/content?limit=50&cursor={optional-cursor}
```

Response:

```json
{
  "items": [
    {
      "sha256": "full-sha256",
      "short_sha": "first-12ish-chars",
      "source_type": "markdown",
      "original_filename": "notes.md",
      "size_bytes": 12345,
      "status": "uploaded",
      "created_at": "2026-06-24T17:52:35Z",
      "updated_at": "2026-06-24T17:52:35Z",
      "published_at": null,
      "private_url": "https://private.usercontent.example/u/full-sha256",
      "public_url": null
    }
  ],
  "next_cursor": null
}
```

- Default limit: 50.
- Sort: newest first.
- Cursor: opaque base64url-encoded JSON token representing DynamoDB pagination state.

### Publish content

Request:

```text
POST /api/content/{sha256}/publish
```

Response: common content item response.

### Unpublish content

Request:

```text
POST /api/content/{sha256}/unpublish
```

Response: common content item response.

### Error response

All API errors should use a stable structured shape:

```json
{
  "error": {
    "code": "upload_too_large",
    "message": "Uploads are limited to 5 MB.",
    "request_id": "request-id"
  }
}
```

Initial error codes:

```text
auth_required
auth_invalid
host_not_allowed
route_not_allowed
validation_error
upload_not_found
upload_expired
upload_not_uploaded
upload_too_large
unsupported_source_type
invalid_utf8
content_not_found
publish_failed
unpublish_failed
storage_error
```

## Authentication and Authorization

### Production private auth

Cloudflare Access protects:

- `share.example.com`
- `private.usercontent.example`

Use separate Cloudflare Access applications and audiences:

```text
Dashboard Access app:
  host = share.example.com
  audience = dashboard audience
  allowed identity = owner email

Private content Access app:
  host = private.usercontent.example
  audience = private content audience
  allowed identity = owner email
```

FastAPI must verify `Cf-Access-Jwt-Assertion` for both private hosts.

Verification requirements:

- Verify signature using Cloudflare Access JWKS.
- Verify issuer/team domain.
- Verify audience for the exact host.
- Verify expiration.
- Verify email claim equals configured allowed email.
- Cache JWKS in memory.
- Fail closed if token is missing or invalid.

### API Gateway defense in depth

API Gateway REST API resource policy must allow only checked-in Cloudflare IP ranges. This is in addition to Cloudflare Access and app-level JWT verification.

### Host/path gate

Implement central host/path gating before route handling:

| Incoming host | Allowed behavior |
| --- | --- |
| `share.example.com` | Dashboard SPA/assets, dashboard API, dashboard robots |
| `private.usercontent.example` | Private root, private robots, private content GET/HEAD |
| `public.usercontent.example` | 403 if it reaches Lambda |
| unknown host | 403 |

Local equivalents are configured only for local development and must not be deployed.

### CSRF and Origin checks

All unsafe dashboard API methods require:

```text
X-Share-CSRF: 1
Origin: https://share.example.com
```

Local development uses the corresponding local dashboard origin.

No FastAPI CORS middleware should be enabled in v1.

## Frontend Requirements

The dashboard frontend is a Vite + React + TypeScript SPA.

Styling:

- Tailwind.
- shadcn/ui with only needed components installed.
- Likely components: button, card, input, label, badge, progress, table, toast/sonner.

Functional requirements:

- Show upload dropzone and file picker.
- Infer source type and allow override.
- Show upload progress using XHR for the S3 POST.
- Use fetch for dashboard JSON API calls.
- Use only relative `/api/*` URLs.
- Show newest-first content library.
- Show private link for every item.
- Show public link only for published items.
- Provide publish/unpublish buttons.
- Show API errors using structured error messages.
- Do not poll in v1.
- Do not store credentials or sensitive tokens in localStorage/sessionStorage.

The built frontend is served by FastAPI using FastAPI's frontend static serving support. Built assets are generated during build and copied into the backend package. Generated static assets are not committed.

## Backend Module Design

Use dependency injection for repositories and services so tests can replace AWS and auth dependencies.

Recommended deep modules:

1. **Access token verifier**
   - Public interface: verify the current request and return an authenticated principal.
   - Encapsulates Cloudflare/local JWT validation, JWKS fetching/caching, host-specific audiences, issuer checks, and email checks.

2. **Host gate**
   - Public interface: decide whether a host/path/method combination is allowed.
   - Encapsulates all host-based route security rules.

3. **Upload service**
   - Public interface: presign upload and finalize upload.
   - Encapsulates upload sessions, S3 temp object validation, size checks, UTF-8 validation, SHA computation, dedupe, raw copy, preview artifact generation, metadata writes, and temp cleanup.

4. **Content renderer**
   - Public interface: render source bytes and source type into artifact bytes.
   - Encapsulates HTML pass-through, Markdown rendering with `wenmode`, Markdown shell generation, and golden-test behavior.

5. **Publish service**
   - Public interface: publish and unpublish content by SHA.
   - Encapsulates idempotency, artifact generation from raw source, public object writes/deletes, metadata updates, and CloudFront invalidation paths.

6. **Metadata repository**
   - Public interface: content lookup, content list with cursor, content upsert/update, upload session create/get/consume.
   - Encapsulates DynamoDB single-table key structure and duplicated metadata consistency.

7. **Object storage adapter**
   - Public interface: temporary object, raw source, private artifact, and public artifact operations.
   - Encapsulates S3 keys, metadata headers, copy/delete behavior, and bucket separation.

8. **URL builder**
   - Public interface: produce private/public URLs for content items.
   - Encapsulates production and local host configuration.

9. **Error mapper**
   - Public interface: convert domain exceptions and validation errors to structured API error responses.

10. **Request/logging middleware**
    - Public interface: attach request IDs, response headers, structured JSON logs, and consistent request context.

Use Pydantic models for API requests, API responses, metadata records, and domain value validation. Service code should raise domain exceptions; API boundary handlers convert them to structured errors.

## Local Development

Daily local development should not use an auth-disabled mode. Instead, use a local Access-compatible proxy.

Local services:

```text
FastAPI dev server: backend API/private route handling
Vite dev server: dashboard HMR
Python local Access-compatible proxy: injects signed Cf-Access-Jwt-Assertion headers
```

Local origins:

```text
http://share.localhost:5174
http://private.localhost:5175
```

Local routing:

```text
share.localhost proxy
  -> Vite dev server
  -> Vite proxies /api/* to FastAPI

private.localhost proxy
  -> FastAPI private content routes
```

Local auth behavior:

- The local proxy signs a fresh JWT per request.
- The local proxy serves a JWKS endpoint.
- The app verifies the local JWT through the same JWKS verification path used for Cloudflare Access.
- Local dashboard and private hosts use separate local audiences.
- Local host/issuer/audience config must never be deployed to production.
- There is no `APP_ENV=local` auth bypass.

Provide a separate production-shape preview command that builds the frontend and serves built assets through FastAPI.

## Infrastructure Requirements

Use Pulumi TypeScript to manage AWS and Cloudflare.

### AWS

- Region: `us-east-1` for all AWS resources.
- Lambda runtime: Python 3.12.
- Lambda architecture: ARM64.
- Lambda memory: 512 MB.
- Lambda timeout: 30 seconds.
- Lambda handler: Mangum-wrapped FastAPI app.
- API Gateway: REST API v1.
- API Gateway custom domains: regional.
- DynamoDB: single metadata table with PITR enabled.
- S3: separate private and public buckets.
- CloudFront: public distribution for `public.usercontent.example` with Origin Access Control.
- ACM: Pulumi-managed certs with DNS validation.
- Logs: API Gateway access logs enabled; Lambda/API logs retained 30 days.
- No EventBridge warmup in v1.
- No CloudWatch alarms in v1.

### Cloudflare

- Pulumi manages DNS records and Access applications/policies.
- Private host DNS records are proxied.
- Public host DNS is DNS-only to CloudFront.
- Separate Access applications for dashboard and private content.
- Access session duration: 7 days.
- Allowed email is configured plainly, not as a secret.

### Cloudflare IP ranges

API Gateway resource policy uses checked-in Cloudflare IP ranges. Do not fetch ranges dynamically during every Pulumi run in v1. A future helper can update/check them.

## Build, Packaging, and CI

Repository organization is a small monorepo with separate backend, frontend, and infrastructure workspaces.

Tooling (versions + tasks):

- `mise` is the single source of truth for dev tool versions (node, python, uv, the Pulumi CLI, hk, oxlint, oxfmt), pinned in `mise.toml` and reproduced via the committed `mise.lock`. It is also the task runner; there is no Makefile.
- The dev/build host runs node 24 and python 3.13. The deployed Lambda runtime stays `python3.12` (see "Runtime split" below).
- Lint/format: `ruff` for Python (lives in the backend `uv` dev group); `oxlint` + `oxfmt` (oxc) for frontend + infra TS/JS only. Typechecking is each workspace's own `tsc`.
- `hk` (configured in `hk.pkl`, installed with `hk install --mise`) runs a single comprehensive pre-commit hook (no pre-push): auto-fixers on staged files, typechecks, and all three test suites (backend pytest, frontend vitest, infra mocha). Each step only fires when a file under its workspace is staged. CI mirrors the same checks. Backend pytest uses session-scoped moto fixtures to keep the suite fast (~12s).

Backend:

- Python dependency management with `uv`.
- Broad/ranged dependencies in project metadata, exact reproducibility through the committed lockfile. `UV_FROZEN=1` (set in `mise.toml`) makes installs use `uv.lock` exactly; the lock is updated deliberately via `mise run relock`.
- `wenmode` should be pinned through the lockfile and tested with golden cases.

Frontend:

- npm with lockfile.
- Vite + React + TypeScript + Tailwind + shadcn/ui. oxlint + oxfmt for lint/format.

Infrastructure:

- npm with lockfile.
- Pulumi TypeScript. oxlint + oxfmt for lint/format.

Supply-chain pin policy:

- Every dependency pins to the newest release at least 72h (3 days) old, to avoid pulling a freshly-compromised version before it is caught and yanked. Enforced on every install via `min-release-age=3` in each workspace `.npmrc` (npm's unit is days) and `UV_FROZEN`/the `relock` task's `--exclude-newer '3 days'` for Python. Renovate (`renovate.json`, `minimumReleaseAge: 3 days`) keeps deps current under the same floor.
- Documented exceptions (carved out by exact pin + `--exclude-newer-package`): `wenmode` (owner-trusted Markdown renderer; 0.7.0 published <72h ago) and `syrupy` (dev-only snapshot tool whose only fixed release is <72h after an upstream version mishap). Both are dev/trusted and re-vetted on bump.

Runtime split (python 3.13 host vs python3.12 Lambda):

- The dev/build host uses python 3.13, but `scripts/build_lambda.py` vendors wheels for `python3.12`/arm64 explicitly (`--python-version 3.12 --python-platform aarch64-manylinux2014 --only-binary :all:`), and `infra` keeps `LAMBDA_RUNTIME = "python3.12"`. So a 3.13 host still produces a correct 3.12 artifact. Bumping the Lambda runtime to 3.13 is a separate, deploy-gated change.

Build/deploy behavior:

- `mise` orchestrates common tasks (`mise run build`, `mise run deploy`, etc.); there is no Makefile.
- Build frontend first.
- Copy built frontend assets into backend package resources.
- Build one Lambda zip containing backend code, vendored dependencies, and built frontend assets.
- Pulumi consumes the prebuilt zip artifact.
- Pulumi preview should not perform expensive build steps.
- V1 uses vendored dependencies in the Lambda zip, not Lambda layers.
- V1 uses local `uv`-based packaging, not Docker, because dependencies are expected to be pure Python. Switch to Docker later if native dependencies are added.
- Deploy remains manual through Pulumi initially (`mise run deploy` = tests + build, then interactive `pulumi up`; never in CI).
- Deploy should run tests and build before `pulumi up`.
- The Pulumi CLI is mise-managed (`aqua:pulumi/pulumi`) pinned to the version that created the current stack state. NOTE: the first deploy after the `@pulumi/aws` v7 upgrade must be run as `pulumi up --refresh --run-program` (v7 adds a `region` field to most resources; this is a one-time, non-destructive state migration — no replacements expected).

Initial CI validation (GitHub Actions; tools provided by `jdx/mise-action`, no setup-uv/setup-node):

- Backend tests, lint, and format check.
- Frontend typecheck and build.
- Infrastructure TypeScript typecheck.
- TS/JS lint (oxlint) + format check (oxfmt).
- No required Pulumi preview in initial CI because stack secrets/config may not be available; no deploy job exists in CI.

## User Stories

1. As the owner, I want to authenticate to `share.example.com` with Cloudflare Access, so that only I can manage content.
2. As the owner, I want a private dashboard, so that I have one place to upload and manage shared documents.
3. As the owner, I want to upload a single HTML file, so that I can share interactive HTML artifacts.
4. As the owner, I want to upload a single Markdown file, so that I can share rendered notes/documents.
5. As the owner, I want uploads private by default, so that nothing is public until I choose publish.
6. As the owner, I want direct browser-to-S3 uploads, so that Lambda does not handle large request bodies.
7. As the owner, I want upload progress, so that I can tell the upload is working.
8. As the owner, I want drag/drop and file picker upload, so that the UI is convenient.
9. As the owner, I want the dashboard to infer source type, so that common files require minimal input.
10. As the owner, I want to override source type, so that unusual filenames still work.
11. As the owner, I want invalid or unsupported files rejected clearly, so that failures are understandable.
12. As the owner, I want the server to compute SHA-256, so that content identity is trustworthy.
13. As the owner, I want duplicate uploads deduplicated, so that identical content has one canonical URL.
14. As the owner, I want a newest-first library, so that recent uploads are easy to find.
15. As the owner, I want pagination, so that the library can grow without scans or huge responses.
16. As the owner, I want every item to show filename, type, size, status, and timestamps, so that I understand my content library.
17. As the owner, I want every item to show a private preview link, so that I can review content before publishing.
18. As the owner, I want published items to show public links, so that I can copy and share them.
19. As the owner, I want one-click publish, so that I can expose content quickly.
20. As the owner, I want one-click unpublish, so that I can remove public access quickly.
21. As the owner, I want publish/unpublish to be retry-safe, so that double-clicks and network retries do not corrupt state.
22. As the owner, I want unpublish to invalidate CloudFront, so that public content disappears quickly.
23. As the owner, I want no delete in v1, so that accidental destructive operations are avoided.
24. As the owner, I want arbitrary HTML/JS supported, so that uploaded artifacts are not artificially limited.
25. As the owner, I want arbitrary raw HTML in Markdown supported, so that Markdown remains expressive.
26. As the owner, I want rendered content isolated from the dashboard origin, so that arbitrary JS cannot reach admin APIs as same-origin code.
27. As the owner, I want rendered content sandboxed without same-origin privileges, so that content is useful but constrained.
28. As the owner, I want dashboard APIs protected by CSRF and Origin checks, so that arbitrary content cannot mutate state cross-site.
29. As the owner, I want no API CORS, so that content origins cannot call dashboard APIs from browsers.
30. As the owner, I want structured errors, so that the UI can present failures cleanly.
31. As the owner, I want request IDs, so that frontend errors correlate with logs.
32. As the owner, I want structured logs, so that Lambda/CloudWatch debugging is practical.
33. As a public visitor, I want published URLs to load without authentication, so that shared content is accessible.
34. As a public visitor, I want both slash and no-slash URLs to work, so that links are forgiving.
35. As a public visitor, I want public content to load quickly, so that it feels like a normal static page.
36. As the system, I want upload sessions and temp objects to expire, so that abandoned uploads clean themselves up.
37. As the system, I want DynamoDB PITR, so that metadata can be recovered from accidental loss.
38. As the developer, I want local development to exercise JWT verification, so that local testing does not hide auth bugs.
39. As the developer, I want a local Access-compatible proxy, so that I can work fully locally without disabling auth.
40. As the developer, I want dependency-injected services/repositories, so that core behavior is easy to test.
41. As the developer, I want golden tests for rendering, so that unsafe/raw Markdown and HTML behavior does not regress.
42. As the developer, I want infrastructure encoded in Pulumi, so that AWS and Cloudflare resources are reproducible.
43. As the developer, I want CI validation but manual deploy initially, so that early iteration remains controlled.

## Testing Decisions

### Testing principles

- Test observable behavior, not implementation details.
- Prefer service-level and route-level tests that assert outcomes, state changes, headers, errors, and artifacts.
- Use dependency injection to replace storage/auth dependencies in tests.
- Use moto for integration-style S3/DynamoDB tests where AWS call shape matters.
- Use pure fakes for service tests where AWS fidelity is not the subject.

### Required backend tests

Authentication and authorization:

- Valid Cloudflare-like JWT accepted.
- Missing JWT rejected.
- Invalid signature rejected.
- Wrong issuer rejected.
- Wrong audience rejected.
- Expired token rejected.
- Wrong email rejected.
- Dashboard audience rejected on private host.
- Private audience rejected on dashboard host.
- Local issuer rejected for production hosts.

Host gate:

- Dashboard host allows dashboard SPA/assets/API/robots.
- Private host allows root/robots/content GET/HEAD only.
- Private host rejects dashboard APIs.
- Public host hitting Lambda returns 403.
- Unknown host returns 403.

CSRF/Origin:

- All dashboard POST endpoints require `X-Share-CSRF: 1`.
- All dashboard POST endpoints require the configured dashboard Origin.
- Cross-origin requests without allowed Origin are rejected.
- No FastAPI CORS headers are emitted for content origins.

Upload/finalize:

- Presign creates upload session and returns presigned POST data.
- Finalize succeeds for valid HTML.
- Finalize succeeds for valid Markdown.
- Finalize rejects missing upload session.
- Finalize rejects expired upload session.
- Finalize rejects missing temporary S3 object.
- Finalize rejects objects over 5 MB.
- Finalize rejects invalid UTF-8.
- Finalize rejects unsupported source type.
- Finalize computes SHA over raw bytes.
- Finalize deduplicates duplicate content.
- Finalize writes raw source, private artifact, metadata, and deletes temp object.

Rendering:

- HTML artifact bytes equal raw upload bytes exactly.
- Markdown renders into the expected shell.
- Raw HTML inside Markdown is preserved.
- JavaScript URLs in Markdown are preserved.
- Tables render as expected.
- Task lists render as expected.
- Golden tests produce readable diffs.

Publish/unpublish:

- Publish from uploaded state creates public object and updates metadata.
- Publish from unpublished state recreates public object and updates metadata.
- Publish is idempotent when already published.
- Publish repairs missing public object when metadata says published.
- Unpublish deletes public object and updates metadata.
- Unpublish is idempotent when already unpublished.
- Unpublish calculates correct CloudFront invalidation paths.

Private content routes:

- Auth required.
- Correct private audience required.
- GET returns artifact with exact security headers.
- HEAD returns expected metadata without body.
- Missing SHA returns structured content-not-found error.
- Responses include `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow`.

API and logging:

- List returns newest-first items and opaque cursor.
- Publish/unpublish/finalize return common content item representation.
- Error responses include stable code, message, and request ID.
- Response headers include request ID.
- Logs include request ID, host, path, user email, action, short SHA/filename when applicable.
- Logs do not include full SHA by default unless explicitly needed.

### Required infrastructure tests/checks

- Public S3 bucket is private and reachable only through CloudFront OAC.
- Private and public buckets are separate.
- Public CloudFront has response headers policy for rendered content security headers.
- Public CloudFront has rewrite function for slash/no-slash content URLs.
- Private hosts are Cloudflare-proxied.
- Public host is DNS-only.
- API Gateway resource policy contains checked-in Cloudflare IP ranges.
- API Gateway access logs are enabled.
- DynamoDB PITR is enabled.
- S3 tmp lifecycle exists.
- Private bucket CORS allows only dashboard origins and POST.

### Frontend tests for v1

- Frontend typecheck must pass.
- Frontend production build must pass.
- No frontend unit tests or Playwright tests are required in v1.

## Out of Scope

- Bundle uploads or zip extraction.
- Uploaded asset directories.
- Mutable/editable content.
- Slugs, aliases, or short links.
- Delete or soft-delete.
- Multi-user workspaces.
- Preview sharing with non-owner users.
- Sanitized/safe HTML mode.
- Content scanning, malware scanning, or external URL scanning.
- Title/description extraction.
- Open Graph image generation.
- Public sitemap.
- Analytics or access logs for public content.
- CloudFront/Lambda@Edge private preview.
- Uploads over 5 MB.
- S3 versioning.
- Storage quotas.
- CloudWatch alarms.
- Automated deploy from CI.
- Lambda layers.
- Docker-based Lambda builds.
- Generated TypeScript API client.
- Production FastAPI docs/OpenAPI.

## Further Notes

- The architecture intentionally treats arbitrary uploaded HTML/JS as untrusted active content even though only the owner can upload. This is why rendered content lives on `usercontent.example`, not on `share.example.com`.
- The CSP sandbox is a defense-in-depth boundary. The most important part is omitting `allow-same-origin`.
- The private content host is read-only by design. Do not add mutation APIs there.
- The dashboard host is sensitive. Do not serve arbitrary uploaded content from it.
- Public content is physically published by writing an object to the public bucket. Unpublishing physically removes the object and invalidates CloudFront.
- Private content should remain accessible only through Cloudflare Access plus app-level JWT verification.
- Future work can add slugs, bundles, metadata extraction, OG previews, public analytics, larger uploads, or edge-authenticated private content without changing the core SHA-addressed model.
