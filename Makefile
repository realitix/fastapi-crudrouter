.PHONY: help install lint lint-fix format check test clean dev-install

# Default target
help:
	@echo "🚀 FastAPI-CRUDRouter Development Commands"
	@echo ""
	@echo "📦 Dependencies:"
	@echo "  install       Install production dependencies"
	@echo "  dev-install   Install development dependencies"
	@echo ""
	@echo "🔍 Code Quality:"
	@echo "  lint          Run all linting tools (ruff, pylint, mypy)"
	@echo "  lint-fix      Run linting with auto-fix where possible"
	@echo "  format        Format code with ruff"
	@echo "  check         Check code formatting without changes"
	@echo "  ruff          Run ruff linting only"
	@echo "  pylint        Run pylint analysis only"
	@echo "  mypy          Run mypy type checking only"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  test          Run all tests"
	@echo "  test-fast     Run tests excluding slow ones"
	@echo ""
	@echo "🧹 Cleanup:"
	@echo "  clean         Clean build artifacts and cache"
	@echo ""

# Dependencies
install:
	@echo "📦 Installing production dependencies..."
	uv sync

dev-install:
	@echo "📦 Installing development dependencies..." 
	uv sync --dev

# Linting and formatting
lint:
	@echo "🔍 Running all linting tools..."
	python3 scripts/lint.py

lint-fix:
	@echo "🔧 Running linting with auto-fix..."
	python3 scripts/lint.py --fix

format:
	@echo "🎨 Formatting code..."
	uv run ruff format fastapi_crudrouter tests

check:
	@echo "🔍 Checking code formatting..."
	python3 scripts/lint.py --check-only

# Individual tools
ruff:
	@echo "🔍 Running ruff..."
	python3 scripts/lint.py ruff

pylint:
	@echo "🔍 Running pylint..."
	python3 scripts/lint.py pylint

mypy:
	@echo "🔍 Running mypy..."
	python3 scripts/lint.py mypy

# Testing
test:
	@echo "🧪 Running all tests..."
	uv run pytest

test-fast:
	@echo "🧪 Running fast tests..."
	uv run pytest -m "not slow"

# Cleanup
clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete

# Development workflow
dev: dev-install lint test
	@echo "🎉 Development setup complete!"

# CI workflow  
ci: install lint test
	@echo "🎉 CI checks passed!"