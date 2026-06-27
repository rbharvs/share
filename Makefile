# Root task runner for the share monorepo.
#
# Workspaces:
#   backend/   FastAPI + Mangum (uv)
#   frontend/  Vite + React (npm)        -- fleshed out in slice 09
#   infra/     Pulumi TypeScript (npm)   -- scaffolded in slice 11, filled 12-14
#
# Slice 01 wires the backend targets end-to-end; slice 11 adds `build` (the
# single Lambda zip) and scaffolds the infra workspace.

BACKEND := backend
FRONTEND := frontend
INFRA := infra

#: Where the built SPA is copied so FastAPI serves it (gitignored). The same
#: location create_app()/StaticSite reads at runtime on Lambda and in preview.
STATIC_DEST := $(BACKEND)/src/share/static

#: The single self-contained Lambda artifact `make build` emits and Pulumi
#: (slice 13) consumes. Gitignored (see `*.zip` / `dist/`).
LAMBDA_ZIP := $(BACKEND)/dist/lambda.zip

.PHONY: help test check format fix dev preview build \
        backend-test backend-check backend-format backend-fix \
        frontend-check frontend-build infra-check infra-test \
        infra-preview deploy boundary-checks

help:
	@echo "Targets: test | check | format | fix | dev | preview | build | deploy"

# --- Aggregate targets ---

test: backend-test infra-test ## Run all test suites

check: backend-check frontend-check infra-check ## Lint + typecheck everything

format: backend-format ## Format all code

fix: backend-fix ## Auto-fix lint + format

dev: ## Run FastAPI + Vite + the local Access proxy together (local dev)
	@echo "share dev: FastAPI :8000  |  Vite :5173  |  Access proxy share.localhost:5174 + private.localhost:5175"
	@echo "Open http://share.localhost:5174"
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(BACKEND) && uv run --group dev uvicorn share.dev_app:app --reload --port 8000 ) & \
	( cd $(FRONTEND) && npm run dev ) & \
	( cd $(BACKEND) && uv run --group dev python -m share.devproxy ) & \
	wait

preview: frontend-build ## Build the SPA and serve it through FastAPI, production-shape
	@echo "share preview: FastAPI serves the built SPA at http://share.localhost:5174 (no Vite)"
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(BACKEND) && uv run --group dev uvicorn share.dev_app:app --port 8000 ) & \
	( cd $(BACKEND) && SHARE_DASHBOARD_UPSTREAM=http://127.0.0.1:8000 uv run --group dev python -m share.devproxy ) & \
	wait

# --- Backend ---

backend-test:
	cd $(BACKEND) && uv run pytest

backend-check:
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .

backend-format:
	cd $(BACKEND) && uv run ruff format .

backend-fix:
	cd $(BACKEND) && uv run ruff check --fix . && uv run ruff format .

# --- Frontend (slice 09) ---

frontend-check:
	@if [ -f $(FRONTEND)/package.json ]; then \
		cd $(FRONTEND) && npm run typecheck; \
	else echo "frontend not scaffolded yet (slice 09)"; fi

# Build the SPA and copy the generated bundle into the backend package, so
# FastAPI serves it exactly as the Lambda will. Generated assets are gitignored.
frontend-build:
	cd $(FRONTEND) && npm run build
	rm -rf $(STATIC_DEST)
	mkdir -p $(STATIC_DEST)
	cp -R $(FRONTEND)/dist/. $(STATIC_DEST)/

# --- Infra (slices 12-14) ---

infra-check:
	@if [ -f $(INFRA)/package.json ]; then \
		cd $(INFRA) && npm run typecheck; \
	else echo "infra not scaffolded yet (slices 12-14)"; fi

# Focused config checks: run the Pulumi program under unit-test mocks (no AWS,
# no `pulumi up`) and assert the data-layer security/PRD invariants.
infra-test:
	@if [ -f $(INFRA)/package.json ]; then \
		cd $(INFRA) && npm test; \
	else echo "infra not scaffolded yet (slices 12-14)"; fi

# Operator-only preview of the real create/update diff. Needs the `share-deploy`
# AWS profile, the Cloudflare token, and the prebuilt $(LAMBDA_ZIP). NEVER run
# in CI — deploy stays manual (see `deploy`).
infra-preview: build
	cd $(INFRA) && pulumi preview

# --- Deploy (manual, slice 14) ---

# The single gated production deploy. Runs the full test suite and builds the
# Lambda zip FIRST, then hands off to the interactive `pulumi up` (its built-in
# yes/no prompt IS the manual gate). There is intentionally NO automated CI
# deploy: CI only validates (see .github/workflows/ci.yml).
#
# After it applies, run `make boundary-checks` to exercise the deployed ingress
# boundaries (Access 200, raw API Gateway 403, public-host-to-Lambda 403, and
# both /u/{sha} URL shapes), and mirror any rotated Access AUDs are already wired
# (they flow from Cloudflare into the Lambda env via the same `pulumi up`).
deploy: test build ## Manual production deploy: tests + build, then gated `pulumi up`
	cd $(INFRA) && pulumi up

# Post-deploy boundary curls (story 42). Reads hosts from the environment or the
# checked-in defaults; see scripts/boundary_checks.sh for the exact assertions.
boundary-checks:
	./scripts/boundary_checks.sh

# --- Packaging (slice 11) ---

# One self-contained Lambda zip: built SPA (copied above by frontend-build) +
# first-party `share` package + vendored deps resolved for the Lambda platform
# (Python 3.12 / ARM64, incl. the native `cryptography` arm64 wheel). No Lambda
# layers, no Docker. Pulumi consumes $(LAMBDA_ZIP) as a prebuilt input.
build: frontend-build ## Build the single Lambda deployment zip for Pulumi
	cd $(BACKEND) && uv run python ../scripts/build_lambda.py --skip-frontend
	@echo "Lambda artifact: $(LAMBDA_ZIP)"
