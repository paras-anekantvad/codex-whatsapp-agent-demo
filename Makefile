.PHONY: help install format format-fix lint lint-fix type-check test sidecar-check check pre-commit fix clean dev

help:
	@echo "Available targets:"
	@echo "  install       - Install all dependencies (uv sync --dev)"
	@echo "  format        - Check code formatting"
	@echo "  format-fix    - Fix code formatting"
	@echo "  lint          - Run linter"
	@echo "  lint-fix      - Fix lint issues"
	@echo "  type-check    - Run type checker (mypy --strict)"
	@echo "  test          - Run tests"
	@echo "  sidecar-check - Verify sidecar JS syntax"
	@echo "  check         - Run all checks (format, lint, type-check, test, sidecar)"
	@echo "  pre-commit    - Alias for check"
	@echo "  fix           - Auto-fix formatting and lint issues"
	@echo "  clean         - Remove build artifacts and caches"
	@echo "  dev           - Run development server"

install:
	uv sync --dev

format:
	uv run ruff format --check .

format-fix:
	uv run ruff format .

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check --fix .

type-check:
	uv run mypy --strict src tests

test:
	uv run pytest -q

sidecar-check:
	node --check sidecar/src/index.js sidecar/src/normalizers.js

check: format lint type-check test sidecar-check
	@echo "All checks passed!"

pre-commit: check

fix: format-fix lint-fix
	@echo "All fixes applied!"

clean:
	rm -rf .venv
	rm -rf .mypy_cache
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .uv-cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned!"

dev:
	uv run uvicorn app.main:app --app-dir src --reload --host 0.0.0.0 --port 8000
