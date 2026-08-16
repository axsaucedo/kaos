---
name: dependabot-fix-all
description: Fix every open Dependabot PR end-to-end on autopilot. Use this skill when asked to run /dependabot-fix-all (no arguments). This skill acts as an orchestrator that discovers all open Dependabot PRs once, triages their CI state, risk-orders the ones that actually need work, then processes them one at a time by spawning an isolated child agent per PR that runs the dependabot-fix skill. It verifies each PR independently via gh, applies the merge policy, records state in a durable ledger, and is bounded so it always terminates. Never pauses for user input.
allowed-tools: shell
---

# Dependabot Fix All

Orchestrate the `dependabot-fix` skill across **every open Dependabot PR**, fully autonomously. Invoked as
`/dependabot-fix-all` (no arguments).

**This session is the orchestrator.** It does not diagnose or edit PRs itself — it spawns **one isolated child agent per PR** (each child runs the heavyweight `dependabot-fix` skill in a fresh context), then **independently verifies** the result via `gh` and moves on. This keeps the orchestrator's context lean and avoids cross-PR contamination.

**The child agent is whatever the host provides.** This skill is deliberately agent-agnostic: it never assumes a particular CLI is installed. See *Phase 1.3 — Spawn the child* for how to pick a backend. A PR whose CI is already green never gets a child at all.

## Core principles (do not violate)

- **Autopilot — never pause.** Zero `ask_user`/interactive prompts anywhere in this path. Resolve every decision
  autonomously. If something cannot be resolved, mark the PR `blocked` and continue.
- **Serial only.** Children share this one git working tree (each runs `gh pr checkout`). Never run children in
  parallel. Clean tree + default branch between children.
- **Bounded — always terminates.** Discover PRs **once** and snapshot the list. Never re-discover inside the loop.
  Attempt each PR **at most once** (no orchestrator-level retry, no re-queue). Every child has a wall-clock timeout.
- **Token-efficient.** **Never read a child's full stdout into context.** Use `tail`/`grep` on its log and treat `gh`
  output as the ground truth for verification.
- **Keep it simple.** No nesting (`dependabot-fix-all` never spawns another `dependabot-fix-all`), no extra retry
  loops, no cleverness beyond what is written here.

Durable state lives in the SQLite `todos` ledger (resumable), not in conversation memory.

---

## Phase 0 — Preflight & discovery (once)

```bash
mkdir -p ./tmp && touch ./tmp/null
REPO=axsaucedo/kaos
```

**Preflight** (abort early with a clear message if any fails):
- `gh auth status` is OK.
- A child-agent backend is available — see *Phase 1.3*. Resolve which one **now**, before the loop, and use the same backend for every PR in the run.
- Git working tree is clean and on the default branch:
  ```bash
  git rev-parse --abbrev-ref HEAD          # expect main
  git status --porcelain                   # expect empty
  ```
  If dirty or on another branch, switch to `main` and confirm clean before proceeding (do not discard user work
  silently — if the tree is dirty with unrelated changes, mark the whole run blocked and report).

**Discover once** and snapshot — this is the *only* discovery; never list PRs again during the loop:

```bash
gh pr list --repo $REPO --author app/dependabot \
  --json number,title,labels,headRefName,files --limit 100 > ./tmp/dfa-prs.json
```

**Risk-order easy → hard** (process low-risk first so the run banks wins before tackling fragile UI majors):

1. `github_actions` / `docker`, and any minor/patch-only bumps
2. `gomod` (operator) — may need `make generate manifests`
3. `uv` / `pip` (pydantic-ai-server, kaos-cli, operator/tests)
4. `npm` in `docs/` or root
5. `npm` in `kaos-ui/` — **framework majors last** (highest risk; may be left open for review)

Infer ecosystem/scope from the PR title, `headRefName`, and `files` (e.g. `/kaos-ui`, `/operator`, `github_actions`).

**Seed the ledger** — one row per discovered PR, in processing order. Use a `dfa-pr-<number>` id convention so rows are
unambiguous:

```sql
-- one INSERT per PR (status pending). Record ecosystem + risk in the description for traceability.
INSERT INTO todos (id, title, description) VALUES
  ('dfa-pr-245', 'Fixing PR #245 (github_actions)', 'ecosystem=github_actions risk=low order=1');
```

Print the ordered plan (PR number, ecosystem, risk) so the run is auditable, then proceed without pausing.

---

## Phase 1 — Serial loop (one PR at a time, in order)

Iterate the snapshot in risk order. For each PR `<n>`:

### 1. Pre-checks (orchestrator, cheap — no child yet)

```bash
gh pr view <n> --repo $REPO --json state,mergeStateStatus,labels,title
```

- If `state` is `MERGED` or `CLOSED` → ledger `done` (note "already merged/closed"), continue.
- Confirm working tree is clean and on `main` before handing off (the previous child should have restored it; if not, `git checkout main` and clean up first).

Mark the ledger row `in_progress`.

### 2. CI triage — decide whether a child is needed at all

**Most Dependabot PRs do not need fixing.** Spawning a child for a PR whose CI is already green wastes 10–30 minutes and risks a child "fixing" something that was never broken. Triage first.

**Always read check state as JSON.** Plain `gh pr checks <n>` renders a **cancelled** run as `fail` in its human output, which makes a concurrency-cancelled or timed-out job look like a genuine failure. Use `--json` and read `state` literally:

```bash
gh pr checks <n> --repo $REPO --json name,state,link > ./tmp/pr-<n>-checks.json
python3 - "$PWD/tmp/pr-<n>-checks.json" <<'PY'
import json, sys
checks = json.load(open(sys.argv[1]))
buckets = {}
for c in checks:
    buckets.setdefault(c["state"], []).append(c["name"])
for state, names in sorted(buckets.items()):
    print(f"{state}: {len(names)} -> {', '.join(sorted(names))}")
PY
```

Classify into exactly one of three triage outcomes:

- **green** — every check is `SUCCESS`/`NEUTRAL`/`SKIPPED`. **No child.** Skip straight to the merge policy (step 6).
- **cancelled-only** — at least one `CANCELLED` and **zero** `FAILURE`/`TIMED_OUT`/`ACTION_REQUIRED`. This is almost always a superseded push (`cancel-in-progress`) or a job that tipped over its `timeout-minutes` — **not** a dependency problem. **No child.** Re-run the workflow and re-triage once:
  ```bash
  gh pr checks <n> --repo $REPO --json name,state,link   # grab a link to get the run id
  gh run rerun <run-id> --failed
  ```
  If it comes back green → merge policy. If it comes back with a real `FAILURE` → treat as genuinely-failing below. Re-run **at most once** per PR; a second cancellation is `blocked`.
- **genuinely-failing** — at least one `FAILURE`, `TIMED_OUT`, or `ACTION_REQUIRED`. **This is the only case that spawns a child.**

If checks are still `PENDING`/`IN_PROGRESS`, wait for them (`gh pr checks <n> --watch --interval 30` with a wall-clock cap of 30 min) before classifying. A cap breach is `blocked`.

Record the triage outcome in the ledger description — it is the audit trail for why a child did or did not run.

### 3. Spawn the child (isolated, non-interactive, with a timeout)

**Only for `genuinely-failing` PRs.** Run **serially** and wait. The child runs the `dependabot-fix` skill in its own fresh context.

**Pick a backend from what the host actually offers** — do not hardcode a vendor. In order of preference:

1. **The host's own subagent mechanism** (e.g. a `Task`/`Agent` tool that spawns a fresh-context child). Preferred: no PATH dependency, no auth setup, works in sandboxed and cloud sessions where no CLI is installed. The child's final message comes back as a return value, so there is no log to parse.
2. **A headless agent CLI already on `PATH`.** Detect, do not assume — e.g. `command -v claude`, `command -v copilot`, `command -v codex`. Invoke it in whatever non-interactive, all-tools-allowed, machine-readable mode that CLI provides, wrapped in `timeout 1800`, with output redirected to `./tmp/pr-<n>-child.log` — **never streamed into context**.
3. **No backend available** → do not fake it. Mark the PR `blocked` with note `no child-agent backend`, and continue.

Whichever backend is used, the child gets the same brief:

> Use the `dependabot-fix` skill to fix Dependabot PR `<n>` fully autonomously. Do not ask any questions; run on autopilot to completion and emit a final `RESULT:` line.

Notes:
- Run from the repo root so the project skill is discoverable.
- `timeout 1800` (30 min) guards against a hung child; a timeout is treated as `blocked`.
- Unattended execution needs the backend's "allow all tools / no approval prompts" mode. If the backend cannot be run without approval prompts, it is not a valid backend for this skill — fall through to the next one.

### 4. Capture the result — token-efficiently (never load the whole log)

Extract **only** the child's final `RESULT:` line and its exit status.

- **Subagent backend** — read the returned final message directly and pull the `RESULT:` line out of it. Nothing else to do.
- **CLI backend** — if the CLI emits JSONL events, parse only the last assistant message plus the terminating result event; if it emits plain text, `grep '^RESULT:' ./tmp/pr-<n>-child.log | tail -1`. Either way, **never** read the full log — it is large.

If no `RESULT:` line is found or the child exited non-zero, treat the run as `blocked` and rely on the step 5 `gh` verification to classify the real PR state.

### 5. Post-checks — independent verification (gh is the ground truth)

Never trust the child's prose; re-derive truth. Use the **same JSON check reading** as step 2 — the cancelled-vs-failed distinction matters just as much here:

```bash
gh pr checks <n> --repo $REPO --json name,state
gh pr view <n> --repo $REPO --json state,mergeStateStatus,labels
```

**In a cloud session, `gh` does not work at all — use the `mcp__github__*` tools.** This is measured behaviour, not a precaution. In a Claude Code cloud session every repo-scoped `gh` call fails: GraphQL returns `403 This GraphQL query is not enabled for this session`, and the REST path that error names (`gh api repos/{owner}/{repo}/...`) returns its own `403 GitHub access is not enabled for this session`. `gh auth status` fails too, because `GH_TOKEN` is the literal placeholder `proxy-injected` and `gh` treats it as an invalid token. Supplying your own `GH_TOKEN` changes nothing. Only non-repo paths such as `gh api user` succeed.

Detect the environment once, at preflight, and pick a lane for the whole run:

```bash
gh api repos/axsaucedo/kaos --jq .full_name >/dev/null 2>&1 && echo "local: use gh" || echo "cloud: use mcp__github__* tools"
```

| Operation | Local | Cloud session |
|---|---|---|
| Read PR / check state | `gh pr view`, `gh pr checks --json` | `mcp__github__pull_request_read`, `mcp__github__get_check_run` |
| Create PR | `gh pr create` | `mcp__github__create_pull_request` |
| Comment | `gh pr comment` | `mcp__github__add_issue_comment` |
| Merge | `gh pr merge --merge` | `mcp__github__merge_pull_request` |
| Re-run / dispatch a workflow | `gh run rerun`, `gh workflow run` | `mcp__github__actions_run_trigger` |

Cloud sessions have **no** tool that writes `refs/tags/*` and **no** branch- or tag-deletion tool. So a cloud run cannot create a tag, cannot delete the `claude/` branches it creates, and must reach a release by dispatching `create-tag.yaml` followed by `release.yaml` at the resulting tag. Merged `claude/` branches accumulate and are reaped outside the session.

Classify the outcome:
- **merged** — `state=MERGED`.
- **green-left-open** — checks green, still open, and it is a kaos-ui framework major (intentional; see merge policy).
- **superseded** — the work was re-homed onto another PR (a `dependabot.yml` split, or a `claude/` replacement branch) and a comment posted on the original; note the replacement PR number.
- **blocked** — checks genuinely failing, child timeout/error, no backend available, or any state that is none of the above.

A PR that never needed a child (triage `green`, or `cancelled-only` that re-ran clean) is classified by the same list — it simply reaches it via the merge policy rather than via a child. Note `no-child-needed` in the ledger so the summary shows how much work was avoided.

### 6. Apply merge policy (auto-merge safe)

Merge only when **all** of these hold:

- `state=OPEN` (not already merged/closed)
- Every check is `SUCCESS`/`NEUTRAL`/`SKIPPED` — **no** `CANCELLED` left unresolved, and the expected check suite actually ran (a PR with zero checks is not green, it is unverified)
- `mergeStateStatus=CLEAN` — reject `BEHIND` (needs a rebase first), `UNSTABLE`, `DIRTY`, `BLOCKED`
- Not a kaos-ui framework major

```bash
gh pr merge <n> --repo $REPO --merge
```

Always a **merge commit** — never squash, never rebase. The child already attempts this in its own Step 9; the orchestrator only acts if the PR is verifiably green but still open. **Never** merge a kaos-ui framework major — leave it open for human review.

#### Never push to a Dependabot branch

A fix commit must never be pushed onto `dependabot/**`. Dependabot force-pushes those branches on its own schedule and will silently discard the work, and some hosts reject the push outright — a cloud/sandboxed session can only push to branches it owns (typically a `claude/`-prefixed branch), and a branch carrying commits authored by someone else, or backing someone else's open PR, is rejected on both counts.

When the fix cannot live on the Dependabot branch, **re-home it**:

1. Branch off the default branch: `git checkout -b claude/deps-<ecosystem>-<short-desc> origin/main`
2. Apply the equivalent dependency bump plus whatever fix the child worked out, and commit.
3. Push that branch and open a PR that states in its body which Dependabot PR it replaces.
4. Comment on the original Dependabot PR pointing at the replacement, then close it.

Ledger this as `superseded` with the replacement PR number in the note. This is the standard path in unattended cloud runs; locally, pushing to the Dependabot branch is still fine when the host allows it.

### 7. Record and continue

Update the ledger row to `done` (with a one-line outcome note: `merged` / `left-open` / `superseded` / `blocked
<reason>`). Restore a clean state for the next child:

```bash
git checkout main && git reset --hard origin/main >/dev/null 2>./tmp/null
git status --porcelain   # expect empty
```

Move to the next PR. **Do not re-discover, do not retry a blocked PR, do not re-queue.**

---

## Phase 2 — Termination & summary

The loop is bounded by the Phase 0 snapshot; once every row is `done`, stop. There is no re-discovery and no retry, so
the run always terminates.

Print a concise summary table built from the ledger — **not** from child logs:

```sql
SELECT id, title, status, description FROM todos WHERE id LIKE 'dfa-pr-%' ORDER BY id;
```

Render as: `PR | ecosystem | outcome | note`. Each child already posted its own REPORT comment on its PR — the
orchestrator does **not** duplicate those. Write the session summary to `./tmp/dfa-summary.md` if useful; **never commit
it**.

Close with a one-paragraph wrap-up: how many merged, how many left open for review, how many superseded, how many
blocked (and the single-line reason for each blocked PR).

---

## Assessment: grouped multi-PR (`/dependabot-fix A,B`) — deferred

Deliberately **not** supported. Dependabot already bundles related dependencies into single grouped PRs, so genuine
cross-PR coupling is rare; serial single-PR runs handle ordering safely on the shared working tree. Batching two PRs
into one child would require two `gh pr checkout`s, intertwined diagnosis, and ambiguous merge/REPORT semantics — more
complexity than value. The orchestrator therefore always runs **one PR per child**. Revisit only if a concrete, repeated
need emerges.

---

## Invariants

- Discover PRs **once**; never re-list inside the loop (prevents endless growth from new bump/version PRs).
- **Triage before spawning.** Read check state as `--json name,state` — never the human-rendered output, which shows `CANCELLED` as `fail`. Only `genuinely-failing` PRs get a child.
- **Agent-agnostic.** Never hardcode a vendor CLI. Detect a backend at preflight; prefer the host's own subagent mechanism; `blocked` if none.
- **Serial** children only (shared git checkout); clean tree + `main` between runs.
- One attempt per PR; no orchestrator retry, no re-queue; at most one workflow re-run per PR; every child has a `timeout`.
- **Never** load full child output into context — extract only the final `RESULT:` line and the exit status; use `gh` as the ground truth.
- **In a cloud session `gh` is unusable** — every repo-scoped call 403s on both GraphQL and REST, and a supplied `GH_TOKEN` does not lift it. Detect at preflight and use `mcp__github__*` for all PR, check and workflow operations. Locally, `gh` is fine.
- A cloud run **cannot create tags and cannot delete branches or tags**. Reach a release by dispatching `create-tag.yaml` then `release.yaml` at the tag; leave `claude/` branch cleanup to a local or scheduled reaper.
- `tmp/` is gitignored — a report file written there needs `git add -f` to be committed.
- **Never push to a `dependabot/**` branch.** Re-home onto a `claude/`-prefixed branch and supersede the original when the host disallows the push.
- Merge only on `state=OPEN` + all checks `SUCCESS`/`NEUTRAL`/`SKIPPED` (and the suite actually ran) + `mergeStateStatus=CLEAN`; always `--merge`, never squash or rebase.
- Fully non-interactive (autopilot); never call `ask_user`.
- Never auto-merge a kaos-ui framework major; leave it open for human review.
- Scratch under `./tmp/` (never `/tmp/`); the SQLite `todos` ledger is the durable, resumable state.
- This skill never spawns another `dependabot-fix-all`.
