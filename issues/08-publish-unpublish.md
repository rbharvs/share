# [08] Publish/Unpublish vertical: POST /api/content/{sha}/publish + /unpublish

**Labels:** ready-for-dev
**User stories:** 18, 19, 20, 21, 22, 23
**Layers cut:** api, service, storage, renderer, schema/data, auth, tests
**Est. production LOC:** ~330

## What to build

Authenticated dashboard POSTs implementing `PublishService`, both idempotent and self-reconciling.

**Publish** regenerates the public artifact from the canonical RAW source (re-rendered via the slice-03 renderer, NOT copied from the private preview), writes `u/{sha}/index.html` to the public bucket, and atomically updates BOTH metadata items (`status=published`, `published_at`, `public_key`). It repairs a missing public object when metadata says published, and reconciles metadata when the object already exists. Republish reuses the same public URL.

**Unpublish** deletes the public object (if present), marks both items `unpublished`, and computes the slash + no-slash CloudFront invalidation paths.

Key decisions:

- **Invalidation behind an `Invalidator` Protocol** with a recording fake, so publish/unpublish is fully testable before any cloud exists. The real CloudFront boto3 client (needs the distribution ID) is dropped in at slice 13; this slice asserts the computed slash/no-slash paths on the fake:
  ```
  /u/{sha}
  /u/{sha}/
  ```
- **Both metadata items always updated atomically** through the same single two-item write helper used by finalize, so the lookup item and list item can never drift. The list item's sort key reuses the immutable `created_at`.
- No content-delete route or state transition exists (story 23 by absence).

## Acceptance criteria

- [ ] Publish from `uploaded` and from `unpublished` both create the public object and update both metadata items; idempotent when already published; repairs a missing public object when metadata says published; reconciles metadata when the object already exists.
- [ ] Public artifact is generated from canonical raw source (re-rendered), not copied from the private preview artifact.
- [ ] Unpublish deletes the public object (if present), marks unpublished, and computes correct slash + no-slash CloudFront invalidation paths (asserted on the recording fake).
- [ ] Both metadata items updated atomically (`status`/`published_at`/`public_key`) so lookup and list never drift.
- [ ] Republish reuses the same public URL; publish/unpublish return the common content-item response; no content-delete route or state transition exists.

## Blocked by

- #03 — Content renderer (public artifact regeneration)
- #05 — Finalize upload (canonical raw source + metadata)
