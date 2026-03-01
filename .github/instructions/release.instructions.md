# Release Instructions

## Quick Reference
```bash
# Tag and release (triggers full release pipeline)
git tag v0.X.Y && git push origin v0.X.Y

# Test release (docs only, no images/PyPI)
git tag v0.0.X && git push origin v0.0.X
```

## Release Artifacts

| Artifact | Destination | Workflow Job |
|----------|------------|--------------|
| Docker: `axsauze/kaos-operator` | Docker Hub | `build-images` |
| Docker: `axsauze/kaos-agent` | Docker Hub | `build-images` |
| Docker: `axsauze/kaos-mcp-python-string` | Docker Hub | `build-images` |
| Helm chart: `kaos-operator` | GitHub Release + gh-pages `/charts/` | `build-helm` + `publish-docs` |
| PyPI: `kaos-cli` | pypi.org | `publish-python` |
| PyPI: `pydantic-ai-server` | pypi.org | `publish-pydantic-ai-server` |
| Docs | gh-pages `/vX.Y.Z/` + `/latest/` | `publish-docs` |
| kaos-ui | kaos-ui gh-pages `/vX.Y.Z/` + `/latest/` | `deploy-ui` |
| GitHub Release | axsaucedo/kaos | `create-release` |
| Standalone releases | axsaucedo/pydantic-ai-server, axsaucedo/kaos-ui | `release-standalone-repos` |
| Version bump PR | main branch | `bump-version` |

## Workflow: release.yaml

Triggered by tags matching `v[0-9]+.[0-9]+.[0-9]+` (excluding `v0.0.*`).

### Job Dependency Graph
```
validate
  ├── tests (unit + E2E)
  │     ├── build-images (3 images × 2 arch)
  │     ├── publish-python (kaos-cli → PyPI)
  │     └── publish-pydantic-ai-server (pais → PyPI)
  ├── build-helm (Helm chart package)
  ├── publish-docs (VitePress → gh-pages)
  └── deploy-ui (kaos-ui → kaos-ui gh-pages)
create-release (needs: validate, build-images, build-helm)
  ├── release-standalone-repos (tags on standalone repos)
  └── bump-version (PR: next dev version)
```

### Version Handling
- The workflow reads version **from the git tag**, NOT from VERSION file
- `sed` commands in publish jobs update pyproject.toml at build time (not committed)
- VERSION file is only updated by the `bump-version` job's PR after release
- Jumping versions (e.g., 0.2.8-dev → v0.3.0) is safe — tag determines version

## Version Files

| File | Format | Example |
|------|--------|---------|
| `VERSION` | `X.Y.Z-dev` | `0.3.1-dev` |
| `kaos-cli/pyproject.toml` | PEP 440: `X.Y.Z.dev0` | `0.3.1.dev0` |
| `pydantic-ai-server/pyproject.toml` | PEP 440: `X.Y.Z.dev0` | `0.3.1.dev0` |
| `operator/chart/Chart.yaml` | `version:` + `appVersion:` | `0.3.1-dev` |
| `operator/chart/values.yaml` | Image tags | `0.3.1-dev` |

## PyPI Trusted Publishers

Both packages use [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/):

| Package | PyPI Project | Workflow File | Environment |
|---------|-------------|---------------|-------------|
| kaos-cli | `kaos-cli` | `release.yaml` | `pypi` |
| pydantic-ai-server | `pydantic-ai-server` | `release.yaml` | `pypi` |

**Config location:** pypi.org → Manage → Publishing → Trusted Publishers

**Critical:** The workflow filename in PyPI config must **exactly match** the GitHub Actions file (`release.yaml`, not `release.yml`).

## Required Secrets

| Secret | Used By | Description |
|--------|---------|-------------|
| `DOCKERHUB_USERNAME` | `build-images` | Docker Hub credentials |
| `DOCKERHUB_TOKEN` | `build-images` | Docker Hub access token |
| `CROSS_REPO_TOKEN` | `release-standalone-repos`, `deploy-ui` | PAT for cross-repo operations |
| `GITHUB_TOKEN` | `create-release`, `bump-version` | Auto-provided by GitHub Actions |

## Required Environments

| Environment | Used By |
|-------------|---------|
| `pypi` | `publish-python`, `publish-pydantic-ai-server` |
| `github-pages` | `publish-docs` (via reusable-docs.yaml) |

## Pre-Release Checklist

1. Ensure all tests pass on main (check latest CI run)
2. Verify PyPI trusted publisher configs match `release.yaml` filename
3. Verify `pypi` environment exists in repo settings
4. Verify Docker Hub credentials are valid
5. Verify `CROSS_REPO_TOKEN` secret exists and has repo scope

## Release Steps

```bash
# 1. Ensure on main with latest code
git checkout main && git pull

# 2. Create and push tag
git tag v0.X.Y
git push origin v0.X.Y

# 3. Monitor workflow
gh run list --workflow=release.yaml --limit 3
gh run watch <run-id>

# 4. Validate artifacts
pip install kaos-cli==0.X.Y
pip install pydantic-ai-server==0.X.Y
curl -sI https://axsaucedo.github.io/kaos/v0.X.Y/
curl -sI https://axsaucedo.github.io/kaos-ui/v0.X.Y/
docker pull axsauze/kaos-operator:0.X.Y
docker pull axsauze/kaos-agent:0.X.Y
docker pull axsauze/kaos-mcp-python-string:0.X.Y

# 5. Merge version bump PR
gh pr list  # find the automated bump PR
gh pr merge <pr-number> --merge
```

## Test Releases

Use `v0.0.*` tags for testing docs deployment only:
```bash
git tag v0.0.99 && git push origin v0.0.99
```
This triggers `test-release.yaml` which only runs `publish-docs` (no images, no PyPI).

## Troubleshooting

### PyPI publish fails with OIDC error
- Verify workflow filename matches PyPI trusted publisher config exactly
- Verify the `pypi` environment exists in repo Settings → Environments
- Verify the publisher config has correct owner/repo/workflow

### Docker push fails
- Check `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets
- Verify Docker Hub account has push access to `axsauze/*` repos

### Standalone repo release fails
- Check `CROSS_REPO_TOKEN` has `repo` scope for target repos
- Verify the standalone repos exist: axsaucedo/pydantic-ai-server, axsaucedo/kaos-ui

### Helm chart not in release
- `build-helm` must complete before `create-release`
- Check artifact upload/download between jobs

### Version bump PR not created
- `create-release` must succeed first
- Check if branch `bump/X.Y.Z-dev` already exists
