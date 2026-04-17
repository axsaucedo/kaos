---
name: dependabot-fix
description: Systematically diagnose and fix a failing Dependabot PR. Use this skill when asked to run /dependabot-fix <pr-number>. The user provides the PR number in their prompt. The skill fetches PR metadata, classifies updates (version vs security), pulls failing-job logs, root-causes the failure, applies targeted fixes on a new branch, runs local validation, opens a replacement PR, and monitors CI until green.
allowed-tools: shell
---

# Dependabot Fix

Systematically fix a failing Dependabot PR. The user provides a PR number (e.g., `/dependabot-fix 142`).

## Step 1: Extract PR Number and Load Context

```bash
PR_NUM=<from user prompt>

gh pr view $PR_NUM --repo axsaucedo/kaos --json title,body,headRefName,files,mergeable
gh pr checks $PR_NUM --repo axsaucedo/kaos
gh pr diff $PR_NUM --repo axsaucedo/kaos | head -200
```

Classify the PR:
- **Ecosystem**: github-actions / npm / uv / go_modules
- **Type**: version-update vs security-update
- **Scope**: single dep vs grouped (patterns, `applies-to`)

## Step 2: Extract Failure Logs

For every failing check, pull logs and identify the first error:

```bash
gh pr checks $PR_NUM --repo axsaucedo/kaos | grep -iE "fail|X"

gh run view --job <JOB_ID> --repo axsaucedo/kaos --log 2>&1 \
  | grep -iE "error|exit code|##\[error\]|FAILED|assert|timed ?out" \
  | head -30
```

Classify the root cause:

| Pattern | Diagnosis | Fix |
|---------|-----------|-----|
| `requires go >= X.Y.Z (running go A.B.C)` | Unpinned `@latest` tool install pulled newer version requiring bumped toolchain | Pin to last version compatible with current `go.mod` |
| `Node.js X is not supported` | Action bumped requires newer Node runner | Verify runner Node version; revert major if needed |
| `upload-artifact: name already exists` | v4+ requires unique names | Add matrix suffix to artifact name |
| CRD / generate drift | API bump changed codegen | `make generate manifests` and commit |
| Test assertion mismatch | Upstream behavior change | Adjust test or pin dep to previous major |
| Post-job cancellation after tests passed | Flaky infra | Rerun failed jobs once |

## Step 3: Branch From Latest Main

```bash
git checkout main && git pull origin main
git checkout -b ci/fix-pr-${PR_NUM}
```

## Step 4: Apply Dependabot's Change

```bash
DB_BRANCH=$(gh pr view $PR_NUM --repo axsaucedo/kaos --json headRefName -q .headRefName)
git fetch origin $DB_BRANCH
DB_SHA=$(git log -1 --format=%H origin/$DB_BRANCH)
git cherry-pick $DB_SHA
```

## Step 5: Apply Targeted Fix

### Unpinned `@latest` Go tool installs

```bash
grep -rn "@latest" .github/workflows operator/Makefile
# Pin to known-good versions, e.g.:
#   controller-tools/cmd/controller-gen@v0.19.0
#   controller-runtime/tools/setup-envtest@release-0.22
#   arttor/helmify/cmd/helmify@v0.4.18
```

### Transitive dep breaking test

Pin the transitive in `pyproject.toml` / `package.json` to the last compatible major.

### CRD drift

```bash
cd operator && make generate manifests && git add -A
```

## Step 6: Local Validation

```bash
mkdir -p ./tmp && touch ./tmp/null

# Go changes
cd operator && make test-unit 2>./tmp/null

# Python changes
cd pydantic-ai-server && source .venv/bin/activate && python -m pytest tests/ -v

# CLI changes
cd kaos-cli && source .venv/bin/activate && python -m pytest tests/ -v

# UI changes
cd kaos-ui && npm run test:unit
```

Only run 1-3 E2E tests locally if CI is showing broad E2E failures; otherwise let CI run the full matrix.

## Step 7: Commit and Open Replacement PR

```bash
git add -A
git commit -m "ci(<scope>): <one-line summary>

<body explaining root cause and fix>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

git push -u origin ci/fix-pr-${PR_NUM}

gh pr create --title "ci: fix #${PR_NUM} — <summary>" \
  --body "Replaces #${PR_NUM} with <fix description>. Closes #${PR_NUM} once merged." \
  --base main
```

## Step 8: Monitor CI

```bash
NEW_PR=$(gh pr list --repo axsaucedo/kaos --head ci/fix-pr-${PR_NUM} --json number -q .[0].number)

while true; do
  STATUS=$(gh pr checks $NEW_PR --repo axsaucedo/kaos 2>&1 | awk -F'\t' '{print $2}' | sort -u)
  echo "$STATUS"
  echo "$STATUS" | grep -qE "pending|queued" || break
  sleep 60
done
```

If any job fails:
1. Get logs for that job
2. Re-diagnose (Step 2)
3. If flake (e.g. "operation was canceled" after tests passed), rerun: `gh run rerun <run-id> --failed`
4. If real regression, apply next fix and push

## Step 9: Merge and Close Original

```bash
gh pr merge $NEW_PR --repo axsaucedo/kaos --merge --delete-branch

gh pr close $PR_NUM --repo axsaucedo/kaos \
  --comment "Superseded by #${NEW_PR} (merged)."
```

## Step 10: Report

Print a summary containing:
- PR number fixed
- Root cause (one line)
- Fix applied (files + change)
- CI result
- Replacement PR number and merge status

## Invariants

- Always branch from latest `main`, never from the dependabot branch directly
- Always cherry-pick dependabot's commit to preserve authorship
- Prefer version pinning over version rollback when dealing with `@latest` drift
- Never push directly to `main`
- Use `./tmp/` (not `/tmp/`) for any local scratch files
- Keep commit messages in conventional-commit format with a body
