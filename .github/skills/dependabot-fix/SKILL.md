---
name: dependabot-fix
description: Comprehensively diagnose and fix a failing Dependabot PR. Use this skill when asked to run /dependabot-fix <pr-number>. The user provides the PR number in their prompt. The skill loads PR context, surveys errors at a high level, ingests relevant repo instructions / docs / source via subagents, performs a deep root-cause diagnosis, designs a risk-tiered fix with a manual testing strategy, ships the fix on a replacement PR, and posts a REPORT.md as a comment on that PR (never commits it).
allowed-tools: shell
---

# Dependabot Fix

Systematically fix a failing Dependabot PR. The user provides a PR number (e.g., `/dependabot-fix 142`).

This skill spans **five phases** (A–E). Do **not** start editing code until Phase D is complete. Do **not** dive into logs until Phase B is complete.

Set up scratch space once at the start:

```bash
mkdir -p ./tmp && touch ./tmp/null
PR_NUM=<from user prompt>
REPO=axsaucedo/kaos
```

---

## Phase A — Context

### Step 1 · PR context

Fetch metadata and produce a one-paragraph written summary of the PR (ecosystem, directory, grouping, size, whether it is a security update, which files it touches). Do **not** open source files yet.

```bash
gh pr view $PR_NUM --repo $REPO --json title,body,headRefName,labels,files,mergeable,createdAt
gh pr diff $PR_NUM --repo $REPO | head -200
```

Identify:
- Ecosystem: `github_actions` | `gomod` | `uv` / `pip` | `npm` | `docker`
- Directory scope (`/`, `operator/`, `pydantic-ai-server/`, `kaos-cli/`, `kaos-ui/`, `operator/tests/`, `mcp-servers/*`, `docs/`)
- Grouping: single-dep vs grouped (`all`, `all-security`)
- Size: list number of files and approximate LOC changed

### Step 2 · High-level error survey

List failing checks and capture the **first and last** error line from each failing job log. Do **not** investigate their meaning yet — just enumerate symptoms.

```bash
gh pr checks $PR_NUM --repo $REPO

# For each failing check, grab job ID from the URL and pull logs
gh run view --job <JOB_ID> --repo $REPO --log 2>./tmp/null \
  | grep -iE "error|exit code|##\[error\]|FAILED|assert|timed ?out" \
  | head -20 > ./tmp/pr-${PR_NUM}-symptoms.txt
```

Output should be a bullet list such as:
- `go-tests/unit-tests`: `controller-tools@v0.20.1 requires go >= 1.25.0`
- `kaos-ui-tests/unit`: `TypeError: Cannot read properties of undefined (reading 'forEach')` in `dashboard.test.ts`
- `python-tests/pydantic-ai-server`: `AssertionError: expected 2 tool calls, got 3`

---

## Phase B — Context ingestion via subagents

Spawn **three parallel `explore` subagents** to load repo knowledge scoped to the touched ecosystems. Do not read any of this yourself beforehand — delegate.

### Step 3 · Instructions subagent

Ask it to read `.github/instructions/*.md` files relevant to the PR's touched paths and summarize conventions, test commands, and gotchas.

Mapping guide (pass relevant ones to the subagent):
- `operator/**` or `gomod` bumps → `operator.instructions.md`, `e2e.instructions.md`
- `pydantic-ai-server/**`, `kaos-cli/**`, `uv` / `pip` bumps → `python.instructions.md`
- `kaos-ui/**` or npm bumps in `kaos-ui/` → `kaos-ui.instructions.md`, `kaos-ui-components.instructions.md`, `kaos-ui-testing.instructions.md`, `kaos-ui-kubernetes-types.instructions.md`
- `docs/**` or npm bumps in `docs/` → `docs.instructions.md`
- `.github/workflows/**` (github_actions PRs) → release/CI-relevant instructions from above, plus `.github/copilot-instructions.md`

### Step 4 · Docs subagent

Ask it to read matching `docs/` pages for the changed modules: module overview, testing notes, architecture diagrams. Return a briefing no longer than ~40 lines covering what the module does, its public surface, and how it is tested.

### Step 5 · Codebase subagent

Ask it to produce a targeted map:
- Primary source directories and entry points for the touched area
- Build and test commands (e.g. `make test-unit`, `npm run test:unit`, `python -m pytest …`)
- Integration/E2E entry points (`operator/tests/e2e`, `kaos-ui/tests/**`)
- Any Makefile targets that generate code (`make generate manifests`, `make helm`)
- Docker images built from this code (for local reproduction)

The three subagent briefings together form the working context for Phase C.

---

## Phase C — Deep root-cause diagnosis

### Step 6 · Diagnose

Now — and only now — dive into the failing-job logs with full context from Phase B. For each failing check, trace the first meaningful error back to:

1. A direct regression from the bumped dep (removed symbol, signature change, behaviour change, stricter validation)
2. A transitive toolchain issue (e.g. `@latest` pulling a newer Go/Node/Python; post-install script requiring newer runtime)
3. Pre-existing test fragility exposed by a harmless dep bump
4. Infra flake (post-job cancellation after tests passed, timeouts, registry rate-limits)

For a grouped PR, diagnose **each** failing check separately — failures may have independent causes. Record findings in `./tmp/pr-${PR_NUM}-diagnosis.md`.

---

## Phase D — Fix design

### Step 7 · Comprehensive plan

Write a plan covering the following; scale depth to risk:

| Section | Always | If risk ≥ medium |
|---|---|---|
| Root cause | ✅ | ✅ |
| Files expected to change | ✅ | ✅ |
| Fix approach (and alternatives considered) | ✅ | ✅ |
| Risk rating (low/medium/high) | ✅ | ✅ |
| Reproduction steps | ✅ | ✅ (must be executable) |
| Manual testing strategy | ✅ | ✅ expanded |
| Rollback plan | | ✅ |
| Blast radius (API / CRD / wire format / user-facing output) | | ✅ |

Risk ≥ medium if **any** of:
- bump touches public API of an exported library (gomod, kaos-cli, pydantic-ai-server)
- changes a Kubernetes CRD generated surface
- changes an HTTP/JSON-RPC wire format
- changes a runtime image that ships in a release

### Step 8 · Manual testing strategy (tiered)

Tier the effort by Step 7's risk rating:

- **Low (isolated)** — apply fix, run the narrowest relevant suite (e.g. one pytest file, one vitest spec, `go test ./pkg/...`). No reproduction step needed.
- **Medium (cross-module or cross-ecosystem)** — first **reproduce** the failure on `main` locally to prove the regression is real (not a harness artefact). Then apply the fix, retest, and confirm the reproduction no longer fires.
- **High (runtime / wire)** — reproduce against a locally-built Docker image for the affected component (see ecosystem appendix). If it touches operator/agent behaviour, bring up a KIND cluster per `.github/instructions/e2e.instructions.md` and run 1–3 E2E tests locally before pushing.

Keep all scratch output under `./tmp/`. Use `./tmp/null` as the sink when suppressing output:

```bash
python -m pytest tests/test_x.py -v 2>./tmp/null
```

---

## Phase E — Finalise

### Step 9 · Ship

```bash
git fetch origin main --quiet
git checkout -b ci/fix-pr-${PR_NUM} origin/main

# Preserve dependabot authorship
DB_BRANCH=$(gh pr view $PR_NUM --repo $REPO --json headRefName -q .headRefName)
git fetch origin $DB_BRANCH
DB_SHA=$(git log -1 --format=%H origin/$DB_BRANCH)
git cherry-pick $DB_SHA

# Apply fix commits (one or several small, focused commits)
# ...make edits...
git add -A
git commit -m "ci(<scope>): <one-line summary>

Root cause: <one sentence>
Fix: <one sentence>
Testing: <how verified>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

git push -u origin ci/fix-pr-${PR_NUM}

gh pr create --base main \
  --title "ci: fix #${PR_NUM} — <summary>" \
  --body "Replaces #${PR_NUM}. Root cause: <...>. Fix: <...>. Closes #${PR_NUM} once merged."
NEW_PR=$(gh pr list --repo $REPO --head ci/fix-pr-${PR_NUM} --json number -q '.[0].number')
```

Monitor CI; rerun known flakes once before investigating:

```bash
gh pr checks $NEW_PR --repo $REPO
# For a known flake after a prior success:
gh run rerun <run-id> --failed --repo $REPO
```

Merge when green, then close the original:

```bash
gh pr merge $NEW_PR --repo $REPO --merge --delete-branch
gh pr close $PR_NUM --repo $REPO --comment "Superseded by #${NEW_PR} (merged)."
```

### Step 10 · REPORT.md as PR comment — never commit

Write `REPORT.md` at the repo root (it is gitignored) covering:
- Original PR context (number, title, ecosystem, scope)
- High-level symptoms (Phase A step 2 output)
- Context ingested (brief bullets per subagent briefing)
- Root cause (Phase C)
- Fix plan with risk rating and testing evidence (Phase D)
- Ship summary: replacement PR, CI status, merge outcome

Then post its contents as a comment on the replacement PR:

```bash
gh pr comment $NEW_PR --repo $REPO --body-file REPORT.md
# Do NOT commit REPORT.md — it lives only locally.
```

---

## Invariants

- Always branch from **latest** `origin/main`, never from the dependabot branch directly
- Always cherry-pick the dependabot commit to preserve authorship
- Prefer version **pinning** over version rollback when dealing with `@latest` toolchain drift
- Never push directly to `main`
- Scratch files live under `./tmp/` (never `/tmp/`); suppress output with `2>./tmp/null`
- Conventional-commit style; include the Copilot co-author trailer
- REPORT.md is **posted as a PR comment**, never committed
- Skip Phase B subagents only if the PR touches a single file that is clearly self-contained (rare)

---

## Appendix · Ecosystem cheat-sheet

Common failure modes observed on bundled Dependabot PRs in this repo. Treat these as hypotheses, not diagnoses — Phase C must still verify.

### `github_actions` (e.g. PR #142)
- `@latest` tool installs in workflows or Makefiles silently bumping to a version that requires a newer Go/Node toolchain
  - *Fix:* pin to the last version compatible with `go.mod` / `.nvmrc` (e.g. `controller-tools@v0.19.0`, `setup-envtest@release-0.22`, `helmify@v0.4.18`)
- `actions/upload-artifact@v4` name-collision within matrix jobs → add a matrix suffix to the artifact name
- `actions/setup-node` major bump dropping support for older Node versions → check `.nvmrc` alignment
- Known flakes to rerun: `e2e/E2E (example-autonomous)` — post-job cancellations and `kaos agent a2a send` exit-1 flakes

### `gomod` (e.g. PR #141)
- `controller-runtime` bumps often require regenerating CRDs and RBAC: `cd operator && make generate manifests`
- `k8s.io/*` bumps may require bumping `setup-envtest` branch (`release-0.X`) to match
- API rename/removal from `sigs.k8s.io/*` — use `go doc <pkg>.<symbol>` in the new version to find the replacement
- Local reproduction: `cd operator && make test-unit`

### `uv` / `pip` (e.g. PR #125, #145)
- `pytest` majors sometimes deprecate fixtures; look for `PytestDeprecationWarning`
- `litellm`, `pydantic-ai` minors can change tool-calling response shape; check `DEBUG_MOCK_RESPONSES` mocks
- `cryptography` majors drop old cipher suites — affects anything using custom TLS
- Local reproduction: `cd <pkg> && source .venv/bin/activate && python -m pytest tests/ -v`
- For E2E deps (`operator/tests/`): `cd operator/tests && source .venv/bin/activate && make e2e-test` (requires KIND)

### `npm` in `kaos-ui/` (e.g. PR #143, #146)
- `vitest` majors change config shape and matcher behaviour
- `react-router` majors change route definitions
- `@tanstack/react-query` majors change `useQuery` signature
- ESLint 9 flat-config drift when `eslint-*` plugins bump
- Local reproduction: `cd kaos-ui && npm ci && npm run build && npm run lint && npm run test:unit`
- Playwright E2E usually only runs in CI for UI PRs; skip locally unless a unit test cannot reproduce

### `npm` in `docs/` or root
- VitePress / mermaid plugin API drift — verify `npm run build` under `docs/`
- Root-level tooling bumps rarely affect runtime; usually a simple rebuild suffices

### `docker`
- Base-image bumps (e.g. `golang:1.25-alpine`) must match `go.mod` toolchain line
- Multi-arch buildx bumps require local `docker buildx create --use`
