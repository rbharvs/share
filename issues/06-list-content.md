# [06] List vertical: GET /api/content with newest-first opaque-cursor pagination

**Labels:** ready-for-dev
**User stories:** 14, 15, 16, 17, 18
**Layers cut:** api, service, storage, schema/data, auth, tests
**Est. production LOC:** ~140

## What to build

An authenticated dashboard `GET /api/content?limit=50&cursor=...` that queries the `USER#default` partition newest-first (sort key `CONTENT#{created_at}#{sha}` descending), maps each domain item to the common content-item response via the URL builder (`private_url` always present; `public_url` only when published), and returns `{items, next_cursor}`.

Key decisions:

- **Opaque cursor** = base64url-encoded JSON token wrapping the DynamoDB `LastEvaluatedKey`. Default limit 50. Resumes without scanning.
- **Read only the `USER#default` partition** — no `Scan`.
- Ordering correctness depends entirely on the `CONTENT#{created_at}#{sha}` sort key; with millisecond `created_at` (slice 05), insertion order is preserved; same-millisecond ties break on SHA, which is documented behavior (fine for a personal tool).

## Acceptance criteria

- [ ] Returns newest-first items and an opaque base64url cursor; default limit 50; cursor decodes to DynamoDB pagination state and resumes without scanning.
- [ ] Each item is the common content-item response with `private_url` present and `public_url` null unless published.
- [ ] Listing reads only the `USER#default` partition (no `Scan`).
- [ ] With a limit smaller than the item count, `next_cursor` round-trips and the second page returns the remaining items with no overlap.
- [ ] Same-second/same-ms ordering documented as SHA-tiebroken (matches the list sort key).

## Blocked by

- #05 — Finalize upload (writes the list items this reads)
