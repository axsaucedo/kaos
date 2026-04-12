---
name: release-kaos
description: Execute a full KAOS release. Use this skill when asked to release a new version of KAOS. The user provides the target version (e.g., v0.5.0) in their prompt. This skill handles pre-flight checks, release creation, CI monitoring, artifact validation, smoke testing, and post-release cleanup.
allowed-tools: shell
---

# Release KAOS

Execute a full release of KAOS. The user provides the target version (e.g., `v0.5.0`) in their prompt.

## Step 1: Extract Version

Extract the version from the user's prompt. It should match `vX.Y.Z` format. Store as `VERSION` (with `v` prefix) and `VERSION_NUM` (without prefix).

```bash
# Example: VERSION=v0.5.0, VERSION_NUM=0.5.0
```

## Step 2: Pre-Flight Checks

Run ALL of these checks before proceeding. Stop and report if any fail.

```bash
# Must be on main with clean working tree
git checkout main && git pull
git status --porcelain  # must be empty

# Verify latest CI on main is green
gh run list --branch main --limit 3 --json conclusion,name

# Verify tag doesn't already exist
git tag -l "$VERSION"  # must be empty
```

## Step 3: Create the Release

Use `gh release create` with auto-generated changelog from PRs:

```bash
gh release create $VERSION --target main --title "$VERSION" --generate-notes
```

This triggers `.github/workflows/release.yaml` which runs ~28 jobs.

## Step 4: Monitor CI Pipeline

Poll the release workflow until ALL jobs complete. Do NOT stop until every job succeeds or fails.

```bash
# Find the release workflow run
gh run list --workflow=release.yaml --limit 3 --json databaseId,status,conclusion

# Watch it (or poll with)
gh run view <RUN_ID> --json jobs --jq '.jobs[] | "\(.name): \(.status) \(.conclusion)"'
```

**Expected jobs:** validate, tests (3 E2E shards + unit), build-images, build-helm, publish-python, publish-pydantic-ai-server, publish-docs, deploy-ui, create-release, release-standalone-repos, bump-version.

**If any job fails:** investigate logs with `gh run view <RUN_ID> --log-failed`, diagnose, fix, and re-trigger if needed.

## Step 5: Validate All Artifacts

Check EVERY artifact. Report status for each.

```bash
# Docker images (3 images)
docker pull axsauze/kaos-operator:$VERSION_NUM
docker pull axsauze/kaos-agent:$VERSION_NUM
docker pull axsauze/kaos-mcp-python-string:$VERSION_NUM

# PyPI packages
pip install kaos-cli==$VERSION_NUM
pip install pydantic-ai-server==$VERSION_NUM

# Documentation
curl -sI https://axsaucedo.github.io/kaos/v$VERSION_NUM/ | head -5
curl -sI https://axsaucedo.github.io/kaos/latest/ | head -5
curl -sI https://axsaucedo.github.io/kaos/dev/ | head -5

# UI
curl -sI https://axsaucedo.github.io/kaos-ui/v$VERSION_NUM/ | head -5
curl -sI https://axsaucedo.github.io/kaos-ui/latest/ | head -5

# Helm chart
helm repo add kaos https://axsaucedo.github.io/kaos/charts/ 2>/dev/null || helm repo update kaos
helm search repo kaos/kaos-operator --versions | head -5

# GitHub Release
gh release view $VERSION --json assets,body | head -20

# Standalone repos
gh release view $VERSION_NUM --repo axsaucedo/pydantic-ai-server 2>&1 | head -5
gh release view $VERSION_NUM --repo axsaucedo/kaos-ui 2>&1 | head -5
```

## Step 6: Docs Race Condition Check

If docs pages return 404, a race condition may have occurred between `release.yaml` and `docs.yaml` deployments:

```bash
# Rebuild the specific version docs
gh workflow run rebuild-docs.yaml -f version=$VERSION_NUM
# Wait ~2 minutes, then re-check
```

## Step 7: Smoke Test on KIND Cluster (if available)

If a KIND cluster is available, upgrade and test:

```bash
# Upgrade operator (always set image tags explicitly — --reuse-values keeps old tags!)
helm upgrade kaos kaos/kaos-operator --version $VERSION_NUM -n kaos-system \
  --set controllerManager.manager.image.tag=$VERSION_NUM \
  --set defaultImages.agentRuntime=axsauze/kaos-agent:$VERSION_NUM \
  --set defaultImages.mcpPythonString=axsauze/kaos-mcp-python-string:$VERSION_NUM \
  --reuse-values

# Verify operator image updated
kubectl get deployment kaos-kaos-operator-controller-manager -n kaos-system \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## Step 8: Merge Version Bump PR

The release pipeline creates an automated PR to bump VERSION to the next dev version. Find and merge it:

```bash
gh pr list --search "bump" --json number,title
gh pr merge <PR_NUMBER> --merge
```

## Step 9: Final Report

Print a summary table of all artifacts and their status:

| Artifact | Status |
|----------|--------|
| Docker images (3) | ✅/❌ |
| PyPI: kaos-cli | ✅/❌ |
| PyPI: pydantic-ai-server | ✅/❌ |
| Docs: version page | ✅/❌ |
| Docs: /latest/ | ✅/❌ |
| Docs: /dev/ | ✅/❌ |
| UI: version page | ✅/❌ |
| Helm chart | ✅/❌ |
| GitHub Release | ✅/❌ |
| Standalone repos | ✅/❌ |
| Bump PR merged | ✅/❌ |

## Troubleshooting Reference

- **PyPI OIDC error:** Verify workflow filename in PyPI trusted publisher config matches `release.yaml` exactly; verify `pypi` environment exists
- **Docker push fails:** Check `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets
- **Standalone repo fails:** Check `CROSS_REPO_TOKEN` has `repo` scope
- **Helm chart missing from release:** `build-helm` must complete before `create-release`
- **Helm upgrade uses old images:** `defaultImages` uses flat strings; `--reuse-values` keeps old tags — always set explicitly
