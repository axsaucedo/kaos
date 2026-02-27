# KAOS-UI Makefile
# Common development operations

.PHONY: help dev build lint test test-smoke test-read test-crud test-functional test-integration clean install

# Default target
help:
	@echo "KAOS-UI Development Commands"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Development:"
	@echo "  dev              Start development server (http://localhost:8081)"
	@echo "  build            Build for production"
	@echo "  build-dev        Build for development with source maps"
	@echo "  lint             Run ESLint"
	@echo "  install          Install dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  test             Run all Playwright tests"
	@echo "  test-smoke       Run smoke tests only"
	@echo "  test-read        Run read tests only"
	@echo "  test-crud        Run CRUD tests only"
	@echo "  test-functional  Run functional tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-ui          Run tests in UI mode"
	@echo "  test-headed      Run tests in headed browser mode"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean            Remove build artifacts and test results"
	@echo ""
	@echo "Prerequisites:"
	@echo "  - KAOS proxy running: kaos ui --no-browser (default port: 8010)"
	@echo "  - Kubernetes cluster with KAOS CRDs installed"

# Development
dev:
	npm run dev

build:
	npm run build

build-dev:
	npm run build:dev

lint:
	npm run lint

install:
	npm ci

# Testing
test:
	npm run test:e2e

test-smoke:
	npx playwright test tests/smoke/ --reporter=list

test-read:
	npx playwright test tests/read/ --reporter=list

test-crud:
	npx playwright test tests/crud/ --reporter=list

test-functional:
	npx playwright test tests/functional/ --reporter=list

test-integration:
	npx playwright test tests/integration/ --reporter=list

test-ui:
	npm run test:e2e:ui

test-headed:
	npx playwright test --headed --reporter=list

# Cleanup
clean:
	rm -rf dist/
	rm -rf test-results/
	rm -rf playwright-report/
	rm -rf node_modules/.vite/
	@echo "Cleaned build artifacts and test results"
