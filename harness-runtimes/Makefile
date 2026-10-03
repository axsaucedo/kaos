.PHONY: help build docker-build test lint format clean run

IMG ?= kaos-harness-pi:latest

help:
	@echo "KAOS harness runtime build targets:"
	@echo "  build               - Install dependencies using UV"
	@echo "  docker-build        - Build the pi harness image"
	@echo "  test                - Run pytest tests"
	@echo "  lint                - Run linting (black check + type check)"
	@echo "  format              - Format code with black"
	@echo "  clean               - Clean build artifacts"
	@echo "  run                 - Run the driver locally on :8000"

# Install dependencies
build:
	uv pip install -e .[dev]

# Build the pi harness image (build context is this directory)
docker-build:
	docker build -f pi/Dockerfile -t $(IMG) .

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

# Run the driver locally
run:
	uv run kaos-harness serve
