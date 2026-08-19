.PHONY: help build test lint format clean

help:
	@echo "KAOS Evals build targets:"
	@echo "  build               - Install dependencies using UV"
	@echo "  test                - Run pytest tests"
	@echo "  lint                - Run linting (black check + type check)"
	@echo "  format              - Format code with black"
	@echo "  clean               - Clean build artifacts"

build:
	uv pip install -e .[runner,dev]

test:
	uv run pytest tests/ -v

lint:
	black --check .
	uvx ty@0.0.55 check

format:
	black .

clean:
	rm -rf build/ dist/ *.egg-info/ __pycache__ .pytest_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
