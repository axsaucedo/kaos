.PHONY: help build docker-build test lint format clean

IMG ?= kaos-memory-service:latest

help:
	@echo "KAOS Memory Service build targets:"
	@echo "  build               - Install dependencies using UV"
	@echo "  test                - Run pytest tests"
	@echo "  lint                - Run linting (black check + type check)"
	@echo "  format              - Format code with black"
	@echo "  clean               - Clean build artifacts"

# Install dependencies
build:
	uv pip install -e .[dev]

# Run tests
test:
	uv run pytest tests/ -v

# Run linting checks (same as CI)
lint:
	black --check .
	uvx ty check

# Format code with black
format:
	black .

# Clean artifacts
clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__ .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
