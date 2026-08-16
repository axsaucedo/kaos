---
applyTo: "{.github/workflows/release.yaml,.github/workflows/test-release.yaml,operator/chart/Chart.yaml,operator/chart/values.yaml}"
paths:
  - ".github/workflows/release.yaml"
  - ".github/workflows/test-release.yaml"
  - "operator/chart/Chart.yaml"
  - "operator/chart/values.yaml"
---

# Release Instructions

## Quick Reference
```bash
# Preview generated notes, add semantic overview, then create release
gh api repos/axsaucedo/kaos/releases/generate-notes \
  -f tag_name=v0.X.Y \
  -f target_commitish=main \
  --jq .body > generated-notes.md
# Review generated-notes.md, write release-notes.md with overview + generated changelog
gh release create v0.X.Y --target main --title "v0.X.Y" --notes-file release-notes.md

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
  ├── build-helm (Helm chart package, updates image tags to release version)
  ├── publish-docs (VitePress → gh-pages)
  └── deploy-ui (kaos-ui → kaos-ui gh-pages)
create-release (needs: validate, build-images, build-helm)
  ├── release-standalone-repos (tags on standalone repos)
  └── bump-version (PR: next dev version, updates all version files including __init__.py)
```

### Version Handling
- The workflow reads version **from the git tag**, NOT from VERSION file
- `sed` commands in publish jobs update pyproject.toml at build time (not committed)
- `build-helm` job updates `values.yaml` image tags to release version before packaging
- VERSION file is only updated by the `bump-version` job's PR after release
- Jumping versions (e.g., 0.2.8-dev → v0.3.0) is safe — tag determines version

## Version Files

| File | Format | Example |
|------|--------|---------|
| `VERSION` | `X.Y.Z-dev` | `0.3.1-dev` |
| `kaos-cli/pyproject.toml` | PEP 440: `X.Y.Z.dev0` | `0.3.1.dev0` |
| `kaos-cli/kaos_cli/__init__.py` | PEP 440 fallback: `X.Y.Z.dev0` | `0.3.1.dev0` |
| `pydantic-ai-server/pyproject.toml` | PEP 440: `X.Y.Z.dev0` | `0.3.1.dev0` |
| `operator/chart/Chart.yaml` | `version:` + `appVersion:` | `0.3.1-dev` |
| `operator/chart/values.yaml` | Image tags | `0.3.1-dev` |

**Note:** `kaos version` uses `importlib.metadata` to read the installed package version dynamically. The `__init__.py` fallback is only used when metadata is unavailable.

## PyPI Trusted Publishers

Both packages use [OIDC trusted publishing](https://docs.pypi.org/trusted-publishers/):

| Package | PyPI Project | Workflow File | Environment |
|---------|-------------|---------------|-------------|
| kaos-cli | `kaos-cli` | `release.yaml` | `pypi` |
| pydantic-ai-server | `pydantic-ai-server` | `release.yaml` | `pypi` |

**Config location:** pypi.org → Manage → Publishing → Trusted Publishers

**Critical:** The workflow filename in PyPI config must **exactly match** the GitHub Actions file (`release.yaml`, not `release.yml`). The repo field must be just the repo name (`kaos`), not the full `owner/repo` path. The environment field should be `pypi`.

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

# 2. Generate and review release notes
gh api repos/axsaucedo/kaos/releases/generate-notes \
  -f tag_name=v0.X.Y \
  -f target_commitish=main \
  --jq .body > generated-notes.md
git log --oneline "$(git describe --tags --abbrev=0 origin/main)"..origin/main
# Write release-notes.md with a semantic overview, grouped highlights, and generated-notes.md preserved under "Generated changelog".

# 3. Create release with reviewed notes
gh release create v0.X.Y --target main --title "v0.X.Y" --notes-file release-notes.md

# 4. Monitor workflow (all 28 jobs should pass)
gh run list --workflow=release.yaml --limit 3
gh run watch <run-id>
# Or check job status:
gh run view <run-id> --json jobs --jq '.jobs[] | "\(.name): \(.status) \(.conclusion)"'

# 5. Validate artifacts
pip install kaos-cli==0.X.Y
pip install pydantic-ai-server==0.X.Y
curl -sI https://axsaucedo.github.io/kaos/v0.X.Y/
curl -sI https://axsaucedo.github.io/kaos-ui/v0.X.Y/
docker pull axsauze/kaos-operator:0.X.Y
docker pull axsauze/kaos-agent:0.X.Y
docker pull axsauze/kaos-mcp-python-string:0.X.Y
helm repo update kaos && helm search repo kaos/kaos-operator --versions | head -5

# 6. Merge version bump PR (auto-created by pipeline)
gh pr list  # find the automated bump PR
gh pr merge <pr-number> --merge
```

### Release Notes Standard

Every release should use generated GitHub notes as the source changelog, but the published body should lead with a reviewed semantic overview:

```markdown
## Overview
One or two short paragraphs describing the release as a coherent product, operator, runtime, CLI, docs, or UI update.

## Highlights
- Group related changes by user-visible outcome or operational impact.
- Mention compatibility, migration, or validation notes when relevant.

## Generated changelog
<GitHub-generated notes / PR list>
```

When updating historical releases, preserve the original generated notes and assets. Add the semantic overview using evidence from the generated changelog, merged PRs, commits between adjacent tags, and changed files. If older releases lack enough context, say that the release is summarized from the available changelog rather than inventing detail.

## Post-Release Validation

### Smoke Test on KIND Cluster
```bash
# Upgrade operator (always set image tags explicitly)
helm upgrade kaos kaos/kaos-operator --version X.Y.Z -n kaos-system \
  --set controllerManager.manager.image.tag=X.Y.Z \
  --set defaultImages.agentRuntime=axsauze/kaos-agent:X.Y.Z \
  --set defaultImages.mcpPythonString=axsauze/kaos-mcp-python-string:X.Y.Z \
  --reuse-values

# Verify operator image
kubectl get deployment kaos-kaos-operator-controller-manager -n kaos-system \
  -o jsonpath='{.spec.template.spec.containers[0].image}'

# Deploy test agent with mock responses
kubectl create namespace release-test
# Apply Agent + ModelAPI resources, verify Ready status
# Test /v1/chat/completions and A2A JSON-RPC endpoints
kubectl delete namespace release-test
```

### Full Validation Checklist
- [ ] All CI jobs passed (28 expected)
- [ ] Docker images: 3 images pullable at version tag
- [ ] PyPI: kaos-cli and pydantic-ai-server installable at version
- [ ] Docs: version page, /latest/, /dev/ all working
- [ ] UI: version page and /latest/ working
- [ ] Helm: chart available in repo at version
- [ ] Standalone repos: releases created on pydantic-ai-server and kaos-ui
- [ ] GitHub Release: has Helm chart asset and PR changelog
- [ ] Bump PR merged
- [ ] Smoke test: operator upgraded, test agent responds correctly

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

### Docs 404 after release (race condition)
When `release.yaml` (publish-docs) and `docs.yaml` (dev docs) deploy concurrently to `github-pages` environment, the later artifact-based deployment may overwrite content. Fix:
```bash
gh workflow run rebuild-docs.yaml -f version=X.Y.Z
# Wait ~2 minutes, then verify
```

### Helm upgrade uses old images
The `defaultImages` in `values.yaml` uses flat strings (e.g., `agentRuntime: axsauze/kaos-agent:X.Y.Z`). When upgrading with `--reuse-values`, old image tags persist. Always set image tags explicitly:
```bash
helm upgrade kaos kaos/kaos-operator --version X.Y.Z -n kaos-system \
  --set controllerManager.manager.image.tag=X.Y.Z \
  --set defaultImages.agentRuntime=axsauze/kaos-agent:X.Y.Z \
  --set defaultImages.mcpPythonString=axsauze/kaos-mcp-python-string:X.Y.Z \
  --reuse-values
```

### Version bump PR not created
- `create-release` must succeed first
- Check if branch `bump/X.Y.Z-dev` already exists
