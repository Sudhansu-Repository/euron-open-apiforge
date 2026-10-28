# Euron Open APIForge: developer entry points. `make` lists every target.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE_DIR := deploy/compose
FLOCI       := docker compose --env-file $(COMPOSE_DIR)/.env -f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.floci.yaml
AWS_LOCAL   := docker compose --env-file $(COMPOSE_DIR)/.env -f $(COMPOSE_DIR)/compose.yaml -f $(COMPOSE_DIR)/compose.aws.yaml
API         := cd apps/api &&
FORGE       := cd apps/forge &&
WEB         := cd apps/web &&
TF_IMAGE    := hashicorp/terraform:1.16.6
TF_ENVS     := local-floci aws-dev aws-prod
# Use a local terraform when installed, otherwise the pinned container.
TF          := $(shell command -v terraform >/dev/null 2>&1 && echo terraform || echo docker run --rm -v $(CURDIR)/infra/terraform:/infra -w /infra $(TF_IMAGE))
TF_ROOT     := $(shell command -v terraform >/dev/null 2>&1 && echo infra/terraform || echo /infra)
ENV         ?= aws-dev
# The demo password make env generated; e2e, qa and bench sign in with it.
DEMO_PW      = $(shell grep -s '^AF_DEMO_PASSWORD=' $(COMPOSE_DIR)/.env | cut -d= -f2)

.PHONY: help env up up-aws down logs ps demo test test-integration migration test-matrix test-corpus e2e qa screenshots bench lint \
        typecheck build openapi sanitize admin aws-deploy aws-migrate aws-admin tf-fmt tf-validate tf-lint tf-security tf-aws-on-floci \
        aws-plan clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─── Local ───────────────────────────────────────────────────────────────────

env: ## Generate deploy/compose/.env with random local-only secrets
	@scripts/gen-local-env.sh

up: env ## Start everything on emulated AWS (Floci), provisioned by the same Terraform as production
	$(FLOCI) up -d --build --wait
	@echo ""
	@echo "  dashboard  http://localhost:$${AF_WEB_PORT:-4610}"
	@echo "  api        http://localhost:$${AF_API_PORT:-4630}/api/v1"
	@echo "  api docs   http://localhost:$${AF_API_PORT:-4630}/docs"
	@echo ""
	@echo "  Next: make demo   (demo users, projects from the bundled specs, generated archives)"

up-aws: env ## Start the stack against real AWS resources (needs deploy/compose/.env.aws)
	@test -f $(COMPOSE_DIR)/.env.aws || { echo "copy $(COMPOSE_DIR)/.env.aws.example to .env.aws first"; exit 1; }
	$(AWS_LOCAL) up -d --build --wait

demo: ## Seed demo users, projects and generations, then print the logins
	$(FLOCI) exec -T api apiforge-server seed-demo
	@echo ""
	@echo "  Sign in at http://localhost:$${AF_WEB_PORT:-4610} with any of:"
	@echo "    owner@apiforge.local    (owner)"
	@echo "    admin@apiforge.local    (admin)"
	@echo "    viewer@apiforge.local   (viewer)"
	@echo "  password: $(DEMO_PW)   (AF_DEMO_PASSWORD in $(COMPOSE_DIR)/.env)"

down: ## Stop the stack and delete its volumes
	-$(FLOCI) down -v --remove-orphans
	-$(AWS_LOCAL) down -v --remove-orphans 2>/dev/null

admin: ## Create or reset an owner on the local stack (EMAIL=you@example.com; prompts for the password)
	@test -n "$(EMAIL)" || { echo "usage: make admin EMAIL=you@example.com"; exit 1; }
	$(FLOCI) exec api apiforge-server create-owner --email "$(EMAIL)"

logs: ## Tail logs (SERVICE=api|worker|web|floci|terraform|migrate)
	$(FLOCI) logs -f --tail 100 $(SERVICE)

ps: ## Show stack status
	$(FLOCI) ps

# ─── Quality ─────────────────────────────────────────────────────────────────

lint: ## Lint the generator and the API (ruff) and the web app (eslint)
	$(FORGE) uv run ruff check src tests && uv run ruff format --check src tests
	$(API) uv run ruff check src tests && uv run ruff format --check src tests
	$(WEB) pnpm lint

typecheck: ## Typecheck the generator and the API (mypy --strict) and the web app (tsc)
	$(FORGE) uv run mypy src
	$(API) uv run mypy src
	$(WEB) pnpm typecheck

test: ## Unit tests: generator and API (pytest) and web (vitest). No database, no network
	$(FORGE) uv run pytest -q
	$(API) uv run pytest tests/unit -q
	$(WEB) pnpm test

test-corpus: ## Slow: generate every bundled spec into a real project and run its gates (--db ones on Postgres too)
	@AF_TEST_DB=generated_test scripts/test-db.sh
	$(FORGE) CORPUS_DATABASE_URL=postgresql+asyncpg://apiforge:apiforge@localhost:$${AF_PG_PORT:-4642}/generated_test \
	  uv run pytest -m corpus

migration: ## Autogenerate an Alembic revision from the models: make migration MSG="add x" (local Postgres)
	@test -n "$(MSG)" || (echo 'usage: make migration MSG="what changed"' && exit 1)
	@scripts/test-db.sh
	$(API) DATABASE_URL=postgresql+asyncpg://apiforge:apiforge@localhost:$${AF_PG_PORT:-4642}/apiforge \
	  sh -c 'uv run apiforge-server migrate && uv run apiforge-server revision -m "$(MSG)"'

test-integration: ## API integration tests against real Postgres and Redis (started if needed)
	@scripts/test-db.sh
	$(API) uv run pytest tests/integration -q --cov --cov-report=term-missing:skip-covered

test-matrix: ## Integration tests under every cache and storage backend (Redis or memory, local disk or Floci S3)
	@scripts/test-matrix.sh

e2e: ## Browser end-to-end tests (Playwright) against the running stack (make up && make demo)
	cd e2e && pnpm install --frozen-lockfile && pnpm exec playwright install chromium && E2E_PASSWORD='$(DEMO_PW)' pnpm test

qa: ## Browser QA sweep (Puppeteer): every page, light and dark, desktop and phone
	cd scripts/qa && pnpm install --frozen-lockfile && QA_PASSWORD='$(DEMO_PW)' node qa.mjs

screenshots: ## README screenshots and the tour GIF from the running demo (after make demo)
	cd scripts/qa && pnpm install --frozen-lockfile && QA_PASSWORD='$(DEMO_PW)' node screenshots.mjs
	scripts/qa/make-tour.sh

bench: ## Measure API latency and generation throughput against the running stack
	$(API) DEMO_PASSWORD='$(DEMO_PW)' uv run python -m apiforge_server.bench

build: ## Build the container images
	$(FLOCI) build

openapi: ## Regenerate docs/api/openapi.yaml from the FastAPI app
	$(API) uv run apiforge-server openapi > ../../docs/api/openapi.yaml

sanitize: ## Scan committable files for credentials, cloud identifiers and em/en dashes
	@scripts/check-sanitization.sh

# ─── Terraform ───────────────────────────────────────────────────────────────

tf-fmt: ## Format all Terraform
	$(TF) fmt -recursive $(TF_ROOT)

tf-validate: ## terraform validate every environment (no backend, no credentials)
	@for env in $(TF_ENVS); do \
	  echo "== $$env"; \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env init -backend=false -input=false -no-color >/dev/null && \
	  $(TF) -chdir=$(TF_ROOT)/envs/$$env validate -no-color || exit 1; \
	done

tf-lint: ## tflint every module and environment (plugins cached in a docker volume)
	docker run --rm -v $(CURDIR)/infra/terraform:/data -v apiforge-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data ghcr.io/terraform-linters/tflint:v0.64.0 --init
	docker run --rm -v $(CURDIR)/infra/terraform:/data -v apiforge-tflint:/plugins -e TFLINT_PLUGIN_DIR=/plugins -w /data ghcr.io/terraform-linters/tflint:v0.64.0 --recursive --format compact

tf-security: ## checkov policy scan of the Terraform
	docker run --rm -v $(CURDIR)/infra/terraform:/tf bridgecrew/checkov:3.3.30 -d /tf --framework terraform --quiet --compact

tf-aws-on-floci: ## Plan, apply, re-plan and destroy the full aws-dev environment against a throwaway Floci
	@scripts/tf-aws-on-floci.sh

aws-deploy: ## One shot: registries, images, infrastructure, migrations, rollout (ENV=aws-dev|aws-prod TAG=...)
	@test -n "$(TAG)" || { echo "usage: make aws-deploy ENV=aws-dev TAG=0.1.0"; exit 1; }
	@scripts/aws-deploy.sh $(ENV) $(TAG)

aws-migrate: ## Run database migrations as a one-off ECS task (ENV=...)
	@scripts/aws-run-task.sh $(ENV) migrate

aws-admin: ## Create the first owner as a one-off ECS task (ENV=... EMAIL=...; APIFORGE_OWNER_PASSWORD in your env)
	@test -n "$(EMAIL)" || { echo "usage: APIFORGE_OWNER_PASSWORD=... make aws-admin ENV=aws-dev EMAIL=you@example.com"; exit 1; }
	@test -n "$$APIFORGE_OWNER_PASSWORD" || { echo "set APIFORGE_OWNER_PASSWORD (at least 10 characters, upper and lower case and a digit)"; exit 1; }
	@scripts/aws-run-task.sh $(ENV) create-owner --email "$(EMAIL)"

aws-plan: ## terraform plan for ENV (aws-dev | aws-prod); needs terraform.tfvars and AWS credentials
	cd infra/terraform/envs/$(ENV) && terraform init -input=false && terraform plan

clean: ## Remove build output and caches
	rm -rf apps/web/.next apps/api/.pytest_cache apps/api/.mypy_cache apps/api/.ruff_cache apps/api/.coverage \
	  apps/forge/.pytest_cache apps/forge/.mypy_cache apps/forge/.ruff_cache apps/forge/.coverage e2e/test-results e2e/playwright-report
