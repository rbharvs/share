# [05] Finalize vertical: POST /api/uploads/finalize

**Labels:** ready-for-dev
**User stories:** 3, 4, 5, 11, 12, 13
**Layers cut:** api, service, storage, renderer, schema/data, auth, tests
**Est. production LOC:** ~385

## What to build

An authenticated dashboard `POST /api/uploads/finalize` that turns a temporary upload into an immutable, SHA-addressed content item and returns the common content-item response.

Flow: load the stored session → head-size-gate the temp object (reject >5 MB *before* download) → read it → validate UTF-8 → compute SHA-256 over raw bytes → dedupe against the metadata repo by SHA → on miss, write `raw/{sha}/source.{html,md}` + `artifacts/{sha}/index.html` (via the slice-03 renderer) and BOTH DynamoDB metadata items atomically → delete the temp object LAST. `source_type`/`filename`/`title` come only from the stored session, never the request body.

Resolved decisions (from spike — presign→finalize→render ran green under moto with byte-exact HTML):

- **Strict ordering** so a mid-finalize crash is retryable and never strands state:
  `validate → SHA → metadata-dedupe → raw-put-if-missing → artifact → upsert BOTH items atomically → delete temp LAST`.
- **Dedupe keys off metadata** (source of truth), NOT `raw_exists` in S3 — otherwise a crashed prior finalize falsely dedupes.
- **Two-item metadata, one transaction** — single `TransactWriteItems` over the lookup item `CONTENT#{sha}/META` and the list item `USER#default/CONTENT#{created_at}#{sha}`:
  ```
  lookup:  pk=CONTENT#{sha}              sk=META
  list:    pk=USER#default               sk=CONTENT#{created_at}#{sha}
  ```
  **GOTCHA (spike-confirmed):** use the low-level `boto3.client("dynamodb")` for the transact — the resource `Table` double-serializes typed JSON and raises `unhashable type: dict` under moto. Use the resource `Table` for get/query. `size_bytes` round-trips low-level `"N"` write → resource `Decimal` read → Pydantic `int` coerce.
- **created_at resolution = millisecond/monotonic** (not 1s), so same-second uploads sort deterministically by insertion in the list sort key.

## Acceptance criteria

- [ ] Finalize succeeds for valid HTML and valid Markdown; SHA computed over raw bytes; duplicate content deduplicated to one canonical item.
- [ ] Rejects: missing session (`upload_not_found`), expired session (`upload_expired`), missing temp object (`upload_not_uploaded`), >5 MB (`upload_too_large` via head-gate before download), invalid UTF-8 (`invalid_utf8`), unsupported source type (`unsupported_source_type`).
- [ ] Ordering: validate → SHA → metadata-dedupe → raw-put-if-missing → artifact → upsert BOTH items atomically → delete temp LAST (mid-finalize crash is retryable; temp survives).
- [ ] Both metadata items carry full metadata and are written in one `TransactWriteItems` via the low-level dynamodb client.
- [ ] Items start as `uploaded`; finalize never trusts client-supplied filename/source_type (taken from session).
- [ ] `size_bytes` round-trips correctly; HTML artifact == raw bytes; both DynamoDB items present and consistent; temp object deleted.

## Blocked by

- #03 — Content renderer
- #04 — Presign upload (ObjectStorage adapter, MetadataRepository, DI chain, session model)
