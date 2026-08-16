---
name: dependabot-fix
description: Comprehensively diagnose and fix a failing Dependabot PR. Use this skill when asked to run /dependabot-fix <pr-number>. The user provides the PR number in their prompt. The skill loads PR context, surveys errors at a high level, ingests relevant repo instructions / docs / source via subagents, performs a deep root-cause diagnosis, designs a risk-tiered fix with a manual testing strategy, commits the fix directly to the Dependabot PR branch, posts a REPORT.md as a comment on it (never commits it), and evaluates whether the skill itself needs updating afterwards.
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

Ask it to read `.github/instructions/*.instructions.md` files relevant to the PR's touched paths and summarize conventions, test commands, and gotchas.

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

### Step 6.5 · Scope triage — is this a fix, or a Dependabot config problem?

Before planning a fix, check whether the PR is **in-scope** for fixing at all. A grouped Dependabot PR that bundles framework-migration majors cannot be fixed in a single pass; the right move is to reconfigure `.github/dependabot.yml` so the majors come through individually.

**Scope-reject triggers** (any one is sufficient):
- A single group PR contains **≥ 2 major bumps** on framework-tier packages
- A major bump on: `react`, `react-dom`, `react-router-dom`, `vite`, `vitest`, `@tanstack/react-query`, `tailwindcss`, `typescript`, `eslint`, `zod`, `zustand` (npm); `controller-runtime`, `k8s.io/*`, `pydantic`, `pydantic-ai`, `litellm` (other ecosystems) when bundled with unrelated updates
- The PR touches > ~40 packages and the majority are routine but a minority are migrations

When triggered, **do not attempt a fix** and **do not close the PR yourself** — leave it open for the host to close. Instead:
1. Update `.github/dependabot.yml` to split the offending group (typically add `update-types: ["minor", "patch"]` to the `all` group so majors get individual PRs).
2. Open that config change as a separate small PR (leave it for the host to review/merge).
3. **Verbalise the scope-reject decision as a comment** on the original Dependabot PR(s): explain why it cannot be fixed in one pass, link the config PR, and recommend the host close it once smaller PRs replace it next cycle. Leave the PR **open** — do not pause for a decision, do not close it.
4. Skip Phase E's "commit on Dependabot branch" flow — there is no fix. The REPORT.md content can be folded into that comment.

Security-update groups (`all-security`) are usually left bundled because security majors are rare and time-sensitive — only split them if a concrete blocker (e.g. a framework major) forces it.

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

### Step 9 · Ship directly on the Dependabot PR

Keep it simple: commit fixes **on the existing Dependabot PR branch**. No replacement PR, no cherry-picking.

```bash
gh pr checkout $PR_NUM --repo $REPO

# ...make edits...
git add -A
git commit -m "ci(<scope>): <one-line summary>

Root cause: <one sentence>
Fix: <one sentence>
Testing: <how verified>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"

git push
```

Monitor CI; rerun known flakes once before investigating:

```bash
gh pr checks $PR_NUM --repo $REPO
gh run rerun <run-id> --failed --repo $REPO  # only for known flakes
```

Merge when green — **but** for kaos-ui framework **major** bumps, leave the PR open for human review instead of merging (see Step 9.5):

```bash
gh pr merge $PR_NUM --repo $REPO --merge
```

**Caveats:**
- Do not use `@dependabot rebase` after pushing fix commits — it will discard them. Let the PR merge as-is.
- If Step 9.5 says leave-open (kaos-ui framework major), **do not merge**. Post the report and leave the PR open; the host merges after their own visual review.

### Step 9.5 · kaos-ui review gate (framework majors only)

The visual/E2E suite for kaos-ui is stringent, so **minor and patch** bumps — including framework packages — can be **merged directly** once CI is green. No human gate is needed for them.

For a kaos-ui **major** bump on a framework package (`react`, `react-dom`, `react-router-dom`, `vite`, `vitest`, `@tanstack/react-query`, `tailwindcss`, `typescript`, `eslint`, `zod`, `zustand`), CI alone is insufficient evidence — major-version visual regressions can slip past Playwright assertions. **Do not merge.** Instead:

1. Push the fix commits so CI is green.
2. Post REPORT.md as a PR comment (Step 10), explicitly noting it is a framework **major** held for human visual review.
3. Leave the PR open. The host reviews and merges manually.

| Bump type (kaos-ui) | Action |
|---|---|
| Minor / patch (any package) | Merge directly when green (Step 9 `gh pr merge`) |
| Major on framework package | **Do NOT merge.** Post report, leave open for human review |

Do not use the `ask_user` tool or any in-chat prompt as a merge gate — it does not reliably block execution. The gate is simply "leave the major PR open"; the human review happens on the PR itself.

### Step 10 · REPORT.md as PR comment — never commit

Write `REPORT.md` at the repo root (gitignored) covering: PR context, symptoms, root cause, fix plan + testing evidence, CI/merge outcome. Then:

```bash
gh pr comment $PR_NUM --repo $REPO --body-file REPORT.md
```

### Step 10.6 · Emit a machine-readable result line

As the **final line of output**, print exactly one status line so an orchestrator (e.g. `/dependabot-fix-all`) can
classify the outcome without parsing prose:

```
RESULT: <merged|left-open|superseded|blocked> pr=<PR_NUM> reason="<short phrase>"
```

- `merged` — fix pushed, CI green, PR merged.
- `left-open` — CI green but intentionally not merged (kaos-ui framework major held for human review).
- `superseded` — scope-rejected; `dependabot.yml` split PR opened + comment posted, original left open for host to close.
- `blocked` — could not be fixed this run (record why in `reason`).

This skill runs **fully non-interactive / autopilot**: never call `ask_user` or ask questions in any mode — resolve
every decision autonomously per the policies above and emit the RESULT line.

### Step 11 · Evaluate skill currency

After the PR merges, ask whether this run surfaced a **major, repeatable** learning that future runs would miss without it. Examples:
- A new failure pattern not in the appendix (new ecosystem, new toolchain)
- A repo-level invariant that changed (e.g. Go toolchain bump, new CI job name)
- A workflow step that proved redundant in practice

If yes — and only if the learning is non-obvious — open a small follow-up PR updating this SKILL.md. Resist adding minor details that a competent operator would infer; bloat degrades the skill.

---

## Invariants

- Work directly on the Dependabot PR branch; do not open replacement PRs
- Never `@dependabot rebase` after pushing fix commits (it discards them)
- Prefer version **pinning** over version rollback for `@latest` toolchain drift
- Scratch files under `./tmp/` (never `/tmp/`); suppress output with `2>./tmp/null`
- Conventional-commit style with Copilot co-author trailer
- REPORT.md is **posted as a PR comment**, never committed
- Runs fully non-interactive (autopilot); the **final output line** is the `RESULT:` status line (Step 10.6)

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
- **Scope-reject first** (see Step 6.5). React / React Router / Vite / Vitest / Zod / Zustand / Tailwind majors bundled with routine bumps = reconfigure `dependabot.yml` and leave the PR open with a comment for the host to close, don't fix.
- Risk is automatically **high** for any kaos-ui PR with a major bump on a framework package — visual regressions do not show up in CI.
- Local reproduction: `cd kaos-ui && npm ci && npm run build && npm run lint && npm run test:unit`
- **Playwright required**, not optional: `npm run test:e2e` against a running dev server + `kaos ui --no-browser` proxy + KIND cluster (per `kaos-ui-testing.instructions.md`). CI's E2E alone is not sufficient evidence.
- **Merge policy** (Step 9.5): kaos-ui **minor/patch** bumps merge directly when CI is green; framework **major** bumps are **left open for human review**, never auto-merged. No `ask_user` gate.
- Common breakage: `vitest` majors change config shape and matcher behaviour; `react-router` majors change route definitions; `@tanstack/react-query` majors change `useQuery` signature; ESLint 9 flat-config drift when `eslint-*` plugins bump.
- **Lockfile desync** is the dominant failure mode on routine grouped PRs — every UI check fails at `npm ci` with `Missing: <pkg> from lock file`. Fix: delete **both** `node_modules` **and** `package-lock.json`, then `npm install`. Deleting only `node_modules` can trigger a secondary `Cannot find native binding` error from `rolldown`/vitest 4.x optional deps.

### `npm` in `docs/` or root
- VitePress / mermaid plugin API drift — verify `npm run build` under `docs/`
- Root-level tooling bumps rarely affect runtime; usually a simple rebuild suffices

### `docker`
- Base-image bumps (e.g. `golang:1.25-alpine`) must match `go.mod` toolchain line
- Multi-arch buildx bumps require local `docker buildx create --use`
