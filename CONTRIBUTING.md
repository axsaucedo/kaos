# Contributing to Agentic Kubernetes Operator

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
   git clone https://github.com/your-org/agentic-kubernetes-operator.git
   cd agentic-kubernetes-operator
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

## Running Tests

### Python Unit Tests

```bash
cd python
source .venv/bin/activate
python -m pytest tests/ -v
```

### Go Integration Tests

```bash
cd operator
make test
```

### E2E Tests (Docker Desktop)

If you have Docker Desktop with Kubernetes enabled:

```bash
cd operator/tests
source .venv/bin/activate
make test
```

### E2E Tests (KIND)

For isolated E2E testing using KIND:

```bash
# Create KIND cluster with local registry and Gateway API
make kind-create

# Run full E2E test suite
make kind-e2e

# Clean up
make kind-delete
```

## CI/CD

### GitHub Actions

The project uses GitHub Actions for CI/CD:

- **`.github/workflows/e2e-tests.yaml`** - Runs E2E tests in KIND cluster on PRs and pushes to main

### Local CI Testing

You can test the GitHub Actions workflow locally using [act](https://github.com/nektos/act):

```bash
act push -W .github/workflows/e2e-tests.yaml
```

Note: Some features may not work identically to GitHub Actions.

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

3. **Run tests locally** before pushing:
   ```bash
   # Python tests
   cd python && python -m pytest tests/ -v
   
   # Go tests
   cd operator && make test
   
   # E2E tests (optional but recommended)
   make kind-e2e
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
