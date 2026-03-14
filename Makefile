.PHONY: help install test lint format typecheck check clean

VENV := .venv/bin

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package in dev mode with all extras
	$(VENV)/pip install -e ".[dev,mcp,knowledge,web]"

test: ## Run tests
	$(VENV)/python -m pytest tests/ -q

test-v: ## Run tests with verbose output
	$(VENV)/python -m pytest tests/ -v

test-cov: ## Run tests with coverage
	$(VENV)/python -m pytest tests/ --cov=ember_code --cov-report=term-missing

lint: ## Run ruff linter
	$(VENV)/ruff check src/ tests/

format: ## Format code with ruff
	$(VENV)/ruff format src/ tests/

format-check: ## Check formatting without making changes
	$(VENV)/ruff format --check src/ tests/

typecheck: ## Run mypy type checking
	$(VENV)/mypy src/ember_code/

check: lint format-check typecheck test ## Run all checks (lint + format + typecheck + test)

fix: ## Auto-fix linting and formatting issues
	$(VENV)/ruff check --fix src/ tests/
	$(VENV)/ruff format src/ tests/

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
