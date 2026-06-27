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

.PHONY: help test check format fix dev \
        backend-test backend-check backend-format backend-fix \
        frontend-check infra-check

help:
	@echo "Targets: test | check | format | fix | dev"

# --- Aggregate targets ---

test: backend-test ## Run all test suites

check: backend-check frontend-check infra-check ## Lint + typecheck everything

format: backend-format ## Format all code

fix: backend-fix ## Auto-fix lint + format

dev: ## Run the backend API locally (uvicorn)
	cd $(BACKEND) && uv run uvicorn share.handler:app --reload --port 8000

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

# --- Infra (slices 12-14) ---

infra-check:
	@if [ -f $(INFRA)/package.json ]; then \
		cd $(INFRA) && npm run typecheck; \
	else echo "infra not scaffolded yet (slices 12-14)"; fi
