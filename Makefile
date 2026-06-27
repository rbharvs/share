# Root task runner for the share monorepo.
#
# Workspaces:
#   backend/   FastAPI + Mangum (uv)
#   frontend/  Vite + React (npm)        -- fleshed out in slice 09
#   infra/     Pulumi TypeScript (npm)   -- fleshed out in slices 12-14
#
# Slice 01 wires the backend targets end-to-end; frontend/infra targets degrade
# gracefully until those workspaces are populated.

BACKEND := backend
FRONTEND := frontend
INFRA := infra

#: Where the built SPA is copied so FastAPI serves it (gitignored). The same
#: location create_app()/StaticSite reads at runtime on Lambda and in preview.
STATIC_DEST := $(BACKEND)/src/share/static

.PHONY: help test check format fix dev preview \
        backend-test backend-check backend-format backend-fix \
        frontend-check frontend-build infra-check

help:
	@echo "Targets: test | check | format | fix | dev | preview"

# --- Aggregate targets ---

test: backend-test ## Run all test suites

check: backend-check frontend-check infra-check ## Lint + typecheck everything

format: backend-format ## Format all code

fix: backend-fix ## Auto-fix lint + format

dev: ## Run FastAPI + Vite + the local Access proxy together (local dev)
	@echo "share dev: FastAPI :8000  |  Vite :5173  |  Access proxy share.localhost:5174 + private.localhost:5175"
	@echo "Open http://share.localhost:5174"
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(BACKEND) && uv run --extra dev uvicorn share.dev_app:app --reload --port 8000 ) & \
	( cd $(FRONTEND) && npm run dev ) & \
	( cd $(BACKEND) && uv run --extra dev python -m share.devproxy ) & \
	wait

preview: frontend-build ## Build the SPA and serve it through FastAPI, production-shape
	@echo "share preview: FastAPI serves the built SPA at http://share.localhost:5174 (no Vite)"
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(BACKEND) && uv run --extra dev uvicorn share.dev_app:app --port 8000 ) & \
	( cd $(BACKEND) && SHARE_DASHBOARD_UPSTREAM=http://127.0.0.1:8000 uv run --extra dev python -m share.devproxy ) & \
	wait

# --- Backend ---

backend-test:
	cd $(BACKEND) && uv run pytest

backend-check:
	cd $(BACKEND) && uv run ruff check .

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
