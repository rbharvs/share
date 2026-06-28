# [11] Packaging, build pipeline, and CI

**Labels:** ready-for-dev
**User stories:** 43
**Layers cut:** infra, tests
**Est. production LOC:** ~250

## What to build

The reproducible build that turns the working app into one deployable Lambda artifact, plus monorepo CI.

Root task runner / Makefile mirroring a [sibling project](https://github.com/rbharvs/habit-tracker)'s `fix`/`check`/`format`/`test`/`dev`, but swapping SAM for:

1. Build the frontend first.
2. Copy built assets into backend package resources.
3. `uv export --no-dev --no-hashes --no-emit-project -o src/requirements.txt` (pinned), vendored into the zip.
4. Produce ONE Lambda zip (backend + vendored deps + built SPA assets) — no Lambda layers, no Docker.

Pulumi consumes the prebuilt zip and does no expensive build work during preview. This slice also scaffolds the Pulumi infra workspace (`Pulumi.yaml`, `package.json`, `tsconfig`, empty stack) so slices 12–14 have a home.

Resolved decision (the one real risk this slice retires): the **`cryptography` native dep** introduced by auth (slice 02) is resolved by fetching the arm64 manylinux wheel via `uv --python-platform` for the Lambda platform — validated here against a real zip. Also migrate `tool.uv.dev-dependencies` → `dependency-groups.dev` (the non-deprecated form).

CI runs the same checks on push: backend test/lint/format, frontend typecheck/build, infra TS typecheck. Deploy stays manual.

## Acceptance criteria

- [ ] Frontend builds first, assets copied into backend package resources, single zip produced for Pulumi to consume; Pulumi preview does no expensive build work.
- [ ] `requirements.txt` regenerated via `uv export` and vendored into the zip (no layers, no Docker); `cryptography` arm64 wheel resolved for the Lambda platform.
- [ ] CI validates backend (test/lint/format), frontend (typecheck/build), and infra (TS typecheck); deploy stays manual.
- [ ] `tool.uv.dev-dependencies` migrated to `dependency-groups.dev`.
- [ ] `make check` green across all three workspaces; `make build` emits a single Lambda zip containing backend, vendored arm64 deps (including `cryptography`), and built SPA assets.

## Blocked by

- #10 — Frontend upload + publish controls (the zip bundles the built frontend; packaging the full real app)
