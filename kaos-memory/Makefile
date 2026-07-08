.PHONY: help build docker-build run-local test lint format clean

IMG ?= axsauze/kaos-memory-service:latest

help:
	@echo "KAOS Memory Service build targets:"
	@echo "  build               - Install dependencies using UV"
	@echo "  docker-build        - Build the container image"
	@echo "  run-local           - Run the service locally in local storage mode"
	@echo "  test                - Run pytest tests"
	@echo "  lint                - Run linting (black check + type check)"
	@echo "  format              - Format code with black"
	@echo "  clean               - Clean build artifacts"

# Install dependencies
build:
	uv pip install -e .[service,dev]

# Build the container image
docker-build:
	docker build -t $(IMG) .

# Run the service locally in local (Chroma + SQLite) mode.
# Override the model endpoint with KAOS_MEMORY_MODEL_BASE_URL for real extraction.
run-local:
	KAOS_MEMORY_STORAGE_TYPE=local \
	KAOS_MEMORY_LOCAL_PATH=$(PWD)/tmp/memory-data \
	KAOS_MEMORY_PORT=8080 \
	python -m kaos_memory

# Run tests
test:
	uv run pytest tests/ -v

# Run linting checks (same as CI)
lint:
	black --check .
	uvx ty@0.0.55 check

# Format code with black
format:
	black .

# Clean artifacts
clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__ .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
