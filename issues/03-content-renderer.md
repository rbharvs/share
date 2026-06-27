# [03] Content renderer: HTML byte-passthrough + Markdown via wenmode into HTML shell

**Labels:** ready-for-dev
**User stories:** 24, 25, 41
**Layers cut:** renderer, schema/data, tests
**Est. production LOC:** ~110 (thin but whole deep module; frozen interface reused by slices 05 and 08)

## What to build

A pure `renderer.render(raw: bytes, source_type, *, title: str) -> bytes` module — a Protocol + factory dispatch (`match`/`assert_never`), zero AWS/IO imports. HTML returns raw bytes byte-for-byte (no sanitize / wrap / inject). Markdown renders through `wenmode` configured for unsafe/raw preservation into a full, self-contained, minimal-CSS HTML document using the original filename as `<title>`.

The signature is **frozen now** because finalize (slice 05) reuses it to make the private artifact and publish (slice 08) reuses it verbatim to regenerate the public artifact from canonical raw source — so private preview and public output can never diverge.

Resolved decisions (from spike — `wenmode` confirmed real: PyPI v0.7.0 by lepture, pure-Python, zero transitive deps, `requires-python >=3.10`):

- **wenmode unsafe config** (preserves raw HTML, `javascript:` URLs, `onclick=`, and GFM tables/task-lists/strikethrough):
  ```python
  Wenmode(rules=presets.github,
          renderer=HTMLRenderer(escape=False, sanitize_urls=False, sanitize_attrs=False))
  ```
  `sanitize_attrs=False` is the faithful reading of the PRD's "preserve unsafe/raw behaviors" and is required to keep `onclick=` etc.
- wenmode 0.7.0 is **Beta** — a minor bump can shift output and break byte-stable goldens. Pin it in the lockfile and lean on golden tests (syrupy single-file `.html` extension, reviewed like code).

## Acceptance criteria

- [ ] HTML artifact bytes equal raw upload bytes exactly (golden + equality assertion).
- [ ] Markdown renders into the expected shell with the original filename as `<title>`; raw HTML inside Markdown preserved; `javascript:` URLs preserved; tables and task lists render.
- [ ] `render()` has zero AWS/IO imports; signature frozen as `render(raw, source_type, *, title) -> bytes`.
- [ ] `wenmode` pinned in the lockfile; golden tests produce readable diffs.
- [ ] Title comes only from the caller (later: the upload session), never trusted from a finalize request body.
- [ ] Opening the generated `.html` artifacts in a browser confirms raw HTML, `javascript:` URLs, GFM tables, and task lists are preserved.

## Blocked by

- #01 — Walking skeleton (project scaffold, source-type model)
