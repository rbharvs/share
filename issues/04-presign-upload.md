# [04] Presign vertical: POST /api/uploads/presign end-to-end

**Labels:** ready-for-dev
**User stories:** 6, 28, 29, 36, 40
**Layers cut:** api, service, storage, schema/data, auth, tests
**Est. production LOC:** ~360

## What to build

An authenticated dashboard `POST /api/uploads/presign` that creates a DynamoDB upload-session item (TTL ~1h via `expires_at_epoch`) and returns a boto3 presigned S3 POST targeting `tmp/{upload_id}` with a content-length-range policy enforcing the 5 MB limit and key prefix.

This is the first product vertical, so it brings up the shared lower layers that later slices extend:

- **ObjectStorage adapter** — bucket config, `tmp/` key helper, `presign_post`, centralized `NoSuchKey`/404 → `None`.
- **MetadataRepository** — upload-session create/get (the two-item content write helper arrives in slice 05).
- **DI chain** mirroring habit-tracker: env-config → `get_*` provider → `Annotated` alias; routes depend on a `UploadService` alias, never on storage directly. Tests override the leaf provider (`get_storage`/`get_repo`) and clear afterward; `@lru_cache` real providers are overridden, not invoked, under moto.
- **CSRF/Origin guard** for all unsafe dashboard methods: require `X-Share-CSRF: 1` AND `Origin: https://share.example.com` (the local dashboard origin in dev). No FastAPI CORS middleware in v1.

Key decisions:

- The presign policy size gate is the **first of two** size gates; the finalize `head_object` gate (slice 05) is the second, and they must stay in sync (both 5 MB).
- Session item carries `created_by` from the verified principal and `original_filename`/`source_type`/`title` — these are read back at finalize and never re-trusted from the finalize body (anti-spoof).
- moto cannot serve the presigned multipart POST in-process; tests assert the returned policy/fields and simulate the browser upload with `put_object`. (A real-S3 / `moto_server` integration check for actual policy enforcement is an optional gated extra — see README open items.)

## Acceptance criteria

- [ ] Presign creates a session and returns presigned POST data with `key=tmp/{upload_id}` and a content-length-range size policy; `max_size_bytes=5242880`.
- [ ] Session item written with `expires_at_epoch` (DynamoDB TTL ~1h) and `created_by` from the verified principal.
- [ ] Dashboard POST requires `X-Share-CSRF: 1` AND the configured dashboard `Origin` (local origin in dev); cross-origin / missing-CSRF rejected with `validation_error`.
- [ ] No FastAPI CORS headers emitted for any origin.
- [ ] DI: routes depend on a `UploadService` alias; tests override `get_storage`/`get_repo` at the leaf and clear afterward; `@lru_cache` real providers are overridden, not invoked, under moto.
- [ ] Unauthenticated / missing-JWT presign is rejected.

## Blocked by

- #02 — Cloudflare Access JWT verifier + local Access proxy
