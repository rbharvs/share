# [10] Frontend upload + publish/unpublish interactions

**Labels:** ready-for-dev
**User stories:** 3, 4, 7, 8, 9, 10, 11, 19, 20, 30
**Layers cut:** frontend, tests
**Est. production LOC:** ~400

## What to build

The interactive dashboard flows on top of the slice-09 shell and the real upload/publish APIs.

- **Upload**: drag/drop + file-picker dropzone; source-type inference from filename/MIME with a visible user override; `POST /api/uploads/presign` → direct-to-S3 XHR upload with a progress bar → `POST /api/uploads/finalize` → insert the new item into the library.
- **Publish/Unpublish**: per-item buttons calling the slice-08 APIs and updating status + public link in place. Double-clicks are safe because the backend is idempotent.
- **CSRF**: `X-Share-CSRF: 1` header on all dashboard POSTs (with the dashboard `Origin`); dashboard JSON calls use `fetch`, the S3 upload uses XHR (for progress).
- **Errors**: rejected / invalid / oversized / unsupported uploads surface the structured error `code` + `message` (toasts). No polling.

## Acceptance criteria

- [ ] Drag/drop and file picker both work; source type inferred from filename/MIME with a visible override control.
- [ ] Upload progress shown via XHR for the S3 POST; dashboard JSON calls use `fetch` with `X-Share-CSRF: 1` and the dashboard `Origin`.
- [ ] Publish/unpublish buttons mutate state in place and reflect new status + public link; double-clicks are safe (backend idempotent).
- [ ] Invalid / unsupported / oversized uploads surface the structured error code + message; no polling.
- [ ] Frontend typecheck and production build pass.
- [ ] `mise run dev`: drag an HTML file → progress bar fills → item appears as `uploaded` with a private link; override a `.txt` to markdown and upload; Publish → public link appears; Unpublish → it disappears.

## Blocked by

- #04 — Presign upload (presign API)
- #05 — Finalize upload (finalize API)
- #08 — Publish/Unpublish (publish/unpublish APIs)
- #09 — Frontend skeleton + library (shell + dev proxy)
