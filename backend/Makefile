.PHONY: help setup test lint format migrate run clean

# Colors
YELLOW := \033[33m
GREEN := \033[32m
RED := \033[31m
RESET := \033[0m

help: ## Show all available commands
	@echo "$(GREEN)AutoApply AI - Backend Commands$(RESET)"
	@echo "================================"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "$(YELLOW)%-20s$(RESET) %s\n", $$1, $$2}'

setup: ## First-time setup: install deps, start Docker, run migrations
	poetry install
	docker compose -f ../docker-compose.yml up -d
	@echo "Waiting for database..."
	@sleep 5
	poetry run alembic upgrade head
	@echo "$(GREEN)✅ Setup complete!$(RESET)"

test: ## Run all tests with coverage report
	poetry run pytest \
		--cov=app \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--cov-fail-under=80 \
		-v

test-unit: ## Run only unit tests (fast)
	poetry run pytest tests/unit -v --tb=short

test-integration: ## Run integration tests (needs Docker services)
	poetry run pytest tests/integration -v

test-watch: ## Re-run tests on file change
	poetry run pytest-watch -- --tb=short -q

lint: ## Check code quality (ruff + black + mypy)
	@echo "$(YELLOW)Running ruff...$(RESET)"
	poetry run ruff check app/ tests/
	@echo "$(YELLOW)Running black...$(RESET)"
	poetry run black --check app/ tests/
	@echo "$(YELLOW)Running mypy...$(RESET)"
	poetry run mypy app/
	@echo "$(GREEN)✅ All linters passed!$(RESET)"

format: ## Auto-format all code
	poetry run ruff check --fix app/ tests/
	poetry run black app/ tests/
	@echo "$(GREEN)✅ Code formatted!$(RESET)"

migrate: ## Run pending database migrations
	poetry run alembic upgrade head
	@echo "$(GREEN)✅ Migrations applied!$(RESET)"

migrate-new: ## Create new migration (usage: make migrate-new msg="add users table")
	poetry run alembic revision --autogenerate -m "$(msg)"

migrate-rollback: ## Rollback last migration
	poetry run alembic downgrade -1
	@echo "$(RED)⚠️  Rolled back one migration$(RESET)"

migrate-history: ## Show migration history
	poetry run alembic history --verbose

run: ## Start development server with hot reload
	poetry run uvicorn app.main:create_app --factory --reload --host 0.0.0.0 --port 8000

run-prod: ## Start production server (no reload)
	poetry run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 4

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name .coverage -delete 2>/dev/null || true
	@echo "$(GREEN)✅ Cleaned!$(RESET)"

db-shell: ## Open PostgreSQL shell
	docker exec -it autoapply-db psql -U autoapply -d autoapply

redis-shell: ## Open Redis CLI
	docker exec -it autoapply-redis redis-cli

docker-up: ## Start all Docker services
	docker compose -f ../docker-compose.yml up -d

docker-down: ## Stop all Docker services
	docker compose -f ../docker-compose.yml down

docker-logs: ## Tail Docker logs
	docker compose -f ../docker-compose.yml logs -f
