# Release Process

This document describes the KAOS release process, versioning strategy, and how documentation is published.

## Version Management

### VERSION File

KAOS uses a single `VERSION` file at the repository root as the source of truth for development versions:

```
0.1.1-dev
```

This version format follows these conventions:
- **Development**: `X.Y.Z-dev` (e.g., `0.1.1-dev`)
- **Release**: `X.Y.Z` (e.g., `0.1.0`) - derived from git tags

### Component Version Formats

Different components use slightly different version formats due to ecosystem requirements:

| Component | Dev Format | Release Format | Example |
|-----------|------------|----------------|---------|
| VERSION file | `X.Y.Z-dev` | `X.Y.Z` | `0.1.1-dev` |
| Helm chart | `X.Y.Z-dev` | `X.Y.Z` | `0.1.1-dev` |
| Python (PEP 440) | `X.Y.Z.dev0` | `X.Y.Z` | `0.1.1.dev0` |
| Docker images | `X.Y.Z-dev` | `X.Y.Z` | `0.1.1-dev` |

## Creating a Release

Releases are triggered by creating a git tag on the `main` branch:

```bash
# Ensure you're on main and up to date
git checkout main
git pull origin main

# Create and push the release tag
git tag v0.1.0
git push origin v0.1.0
```

### Release Workflow

When a tag matching `v*` is pushed, the release workflow automatically:

1. **Validates** the version format and checks tests pass
2. **Builds Docker images** for operator and agent runtimes
3. **Publishes images** to Docker Hub with the release version tag
4. **Packages Helm chart** with the release version
5. **Publishes Python package** (kaos-cli) to PyPI
6. **Deploys versioned documentation** to GitHub Pages
7. **Creates GitHub Release** with auto-generated release notes
8. **Bumps version on main** by creating a PR for the next dev version

### Version Bumping

After a release, the workflow automatically:
- Creates a branch `bump/X.Y.(Z+1)-dev`
- Updates VERSION file to `X.Y.(Z+1)-dev`
- Updates Python package versions to `X.Y.(Z+1).dev0`
- Updates Helm chart version to `X.Y.(Z+1)-dev`
- Opens a PR to merge these changes to main

Example: Releasing `v0.1.0` creates a PR to bump to `0.1.1-dev`.

## Documentation Versioning

### Multi-Version Structure

Documentation is published to GitHub Pages with the following structure:

- `/kaos/` → Redirects to `/kaos/latest/`
- `/kaos/dev/` → Development documentation (from `main` branch)
- `/kaos/latest/` → Latest stable release documentation
- `/kaos/vX.Y.Z/` → Immutable documentation for specific releases

### Version Switcher

The documentation includes a version switcher in the navigation bar that dynamically lists available versions based on git tags.

### When Docs Are Published

- **Dev docs** (`/kaos/dev/`): Updated on every push to `main` that changes the docs
- **Release docs** (`/kaos/vX.Y.Z/` and `/kaos/latest/`): Published when a release tag is created

## Helm Chart Repository

The Helm chart is available at:

```bash
helm repo add kaos https://axsaucedo.github.io/kaos/charts
helm repo update
helm search repo kaos
```

Both development and release versions are published:
- Dev versions: `X.Y.Z-dev` (from main branch)
- Release versions: `X.Y.Z` (from release tags)

## PyPI Package

The kaos-cli package is published to PyPI only for releases:

```bash
pip install kaos-cli
```

Development versions are not published to PyPI. For development, install directly from source:

```bash
cd kaos-cli
pip install -e .
```

## Design Decisions

### Why Tag-Triggered Releases?

Using git tags to trigger releases keeps the process simple:
- No release branches to maintain
- No manual version editing required
- Clear audit trail through git history
- Easy to create hotfix releases on any commit

### Why Always +1 Patch for Bumps?

After each release, the patch version is always incremented by 1. For major or minor version bumps, simply create the appropriate tag:

- Current: `0.5.9-dev`
- Want to release `0.6.0`: Tag as `v0.6.0`
- Bump creates PR for: `0.6.1-dev`

This keeps the automation simple while supporting semantic versioning.

### Why Separate Dev and Release Docs?

Keeping development documentation at `/kaos/dev/` allows:
- Users to see upcoming features
- Contributors to reference latest docs
- Clear distinction between stable and in-progress content
