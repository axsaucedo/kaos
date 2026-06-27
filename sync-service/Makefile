.PHONY: help install lint format test

help:
	@echo "KAOS sync service targets:"
	@echo "  install - Create venv and install the package with dev extras"
	@echo "  lint    - Run black --check and ty type checking"
	@echo "  format  - Format code with black"
	@echo "  test    - Run unit tests"

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -e '.[dev]'

lint:
	black --check .
	uvx ty check

format:
	black .

test:
	python -m pytest tests/ -v
