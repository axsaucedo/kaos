.PHONY: help build docker-build test lint format clean run

IMG ?= kaos-runtime:latest

help:
	@echo "Agent Runtime build targets:"
	@echo "  build               - Install dependencies using UV"
	@echo "  docker-build        - Build runtime Docker image"
	@echo "  test                - Run pytest integration tests"
	@echo "  lint                - Run linting (black check + type check)"
	@echo "  format              - Format code with black"
	@echo "  clean               - Clean build artifacts"
	@echo "  run                 - Run server locally"

# Install dependencies
build:
	uv pip install -e .[dev]

# Build Docker image
docker-build: build
	docker build -t ${IMG} .

# Run integration tests
test:
	uv run pytest tests/ -v --cov=. --cov-report=html

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

# Run server locally
run:
	uv run python -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
