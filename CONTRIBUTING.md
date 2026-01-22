# Contributing to KAOS (K8s Agent Orchestration System)

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Go 1.24+
- Python 3.12+
- Docker
- kubectl
- Helm 3+
- KIND (for E2E testing)

### Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/kaos.git
   cd kaos
   ```

2. **Set up Python environment:**
   ```bash
   cd python
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. **Build the operator:**
   ```bash
   cd operator
   make build
   ```

## Project Structure

```
kaos/
├── python/                    # Agent runtime framework
│   ├── Makefile               # Python build and test targets
│   └── tests/                 # Python unit tests
├── operator/                  # Kubernetes operator (Go/kubebuilder)
│   ├── Makefile               # Operator build, test, and E2E targets
│   ├── hack/                  # CI/CD scripts and utilities
│   │   ├── run-e2e-tests.sh   # Main E2E test runner
│   │   ├── build-push-images.sh
│   │   ├── kind-with-registry.sh
│   │   ├── install-gateway.sh
│   │   └── install-metallb.sh
│   └── tests/                 # E2E test suite
└── .github/workflows/         # GitHub Actions
    ├── e2e-tests.yaml         # E2E tests in KIND
    ├── go-tests.yaml          # Go unit tests
    └── python-tests.yaml      # Python unit tests
```

## Running Tests

**IMPORTANT**: CI runs both tests AND linting. Always run both before pushing.

### Python Unit Tests and Linting

```bash
cd python
source .venv/bin/activate

# Run tests (39 tests)
python -m pytest tests/ -v

# Run linting (required for CI to pass)
make lint  # Runs: black --check . && uvx ty check

# Format code if black fails
make format
```

### Go Integration Tests

```bash
cd operator
make test-unit
```

### E2E Tests (Docker Desktop)

If you have Docker Desktop with Kubernetes enabled:

```bash
cd operator
# Build images and run tests
make e2e-test
```

### E2E Tests (KIND)

For isolated E2E testing using KIND:

```bash
cd operator

# Create KIND cluster with local registry and Gateway API
make kind-create

# Run full E2E test suite (builds images, installs operator, runs tests)
make kind-e2e-run-tests

# Or run tests on existing cluster (operator must be installed)
make e2e-test

# Clean up
make kind-delete
```

## CI/CD

### GitHub Actions

The project uses GitHub Actions for CI/CD:

- **`.github/workflows/e2e-tests.yaml`** - E2E tests in KIND (triggered by operator/ or python/ changes)
- **`.github/workflows/go-tests.yaml`** - Go unit tests (triggered by operator/ changes)
- **`.github/workflows/python-tests.yaml`** - Python unit tests (triggered by python/ changes)

All workflows are triggered on PRs and pushes to `main`, with path filters to avoid unnecessary runs.

### Local CI Testing

You can test some GitHub Actions workflows locally using [act](https://github.com/nektos/act):

```bash
# Test Python tests (works well)
act -j python-tests --container-architecture linux/amd64

# Test Go tests (may fail due to envtest limitations in Docker)
act -j go-tests --container-architecture linux/amd64
```

**Note:** Go integration tests may fail in `act` due to envtest control plane limitations in Docker, especially on ARM machines. These tests work correctly in the actual GitHub Actions runners.

## Code Style

### Python

- Follow PEP 8
- Use type hints
- Use async/await for I/O operations

### Go

- Follow standard Go conventions
- Run `gofmt` before committing
- Run `make manifests` after modifying CRD types

## Pull Request Process

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes** with clear, atomic commits

3. **Run tests and linting locally** before pushing:
   ```bash
   # Python tests + linting (both required for CI)
   cd python && source .venv/bin/activate
   python -m pytest tests/ -v
   make lint
   
   # Go tests
   cd operator && make test-unit
   
   # E2E tests (optional but recommended)
   cd operator && make kind-create
   cd operator && make kind-e2e-run-tests
   ```

4. **Push and create a PR** against `main`

5. **Ensure CI passes** - all tests must pass before merging

## Commit Messages

Use clear, descriptive commit messages:

```
feat: Add support for custom resource annotations

- Add annotation parsing in controller
- Update CRD with annotation field
- Add tests for annotation handling
```

Prefix types:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `test:` - Test additions or modifications
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

## Documentation

When making changes:

1. Update `CLAUDE.md` for significant changes
2. Update relevant files in `docs/` directory
3. Update inline code comments where needed

## Getting Help

- Open an issue for bugs or feature requests
- Check existing issues before creating new ones
- Use discussions for questions and ideas

## Release Process

See [docs/development/releasing.md](docs/development/releasing.md) for details on:

- Version management and the `VERSION` file
- Creating releases via git tags
- Documentation versioning
- Helm chart and PyPI publishing

In brief, releases are created by tagging `main`:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release workflow then automatically builds, tests, publishes, and creates a GitHub Release.
