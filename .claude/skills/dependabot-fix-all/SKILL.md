---
name: dependabot-fix-all
description: Fix every open Dependabot PR end-to-end on autopilot. Use this skill when asked to run /dependabot-fix-all (no arguments). This skill acts as an orchestrator that discovers all open Dependabot PRs once, risk-orders them, then processes them one at a time by spawning an isolated non-interactive agent child per PR (e.g. depending on your harness `claude -p`, `copilot -p`, etc.) that runs the dependabot-fix skill. It verifies each PR independently via gh, applies the merge policy, records state in a durable ledger, and is bounded so it always terminates. Never pauses for user input.
allowed-tools: shell
---

# Dependabot Fix All

Orchestrate the `dependabot-fix` skill across **every open Dependabot PR**, fully autonomously. Invoked as
`/dependabot-fix-all` (no arguments).

**This session is the orchestrator.** It does not diagnose or edit PRs itself — it spawns **one isolated
non-interactive agent child per PR** (each child runs the heavyweight `dependabot-fix` skill in a fresh context), then
**independently verifies** the result via `gh` and moves on. This keeps the orchestrator's context lean and avoids
cross-PR contamination.

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
- The agent CLI is on `PATH` (e.g. `command -v claude`).
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
- Confirm working tree is clean and on `main` before handing off (the previous child should have restored it; if not,
  `git checkout main` and clean up first).

Mark the ledger row `in_progress`.

### 2. Spawn the child (isolated, non-interactive, with a timeout)

Run **serially** and wait. The child is your agent CLI's non-interactive/prompt mode running the `dependabot-fix`
skill in a fresh context — the harness does not matter, only these requirements:

- **Prompt:** "Use the dependabot-fix skill to fix Dependabot PR `<n>` fully autonomously. Do not ask any questions;
  run on autopilot to completion and emit the final RESULT line."
- **Unattended:** grant whatever tool/path permissions the harness needs to run without approval prompts.
- **JSON output to a log file** (`./tmp/pr-<n>-child.jsonl`), never streamed into context — plain text output
  redirected to a file is unreliable across harnesses; the JSON events reliably carry the final reply.
- **Wall-clock guard:** wrap in `timeout 1800` (30 min); a timeout is treated as `blocked` (see classification).
- Run from the repo root so the project skill is discoverable, and capture the child's exit code.

### 3. Capture the result — token-efficiently (never load the whole JSONL)

Extract **only** the `RESULT:` line and the success/error flag from the log's terminal result event. Do not read the
full log — it is large. Use a small script (e.g. `python3` over the JSONL) that scans for the harness's terminal
event: the final assistant reply carries the `RESULT:` line, and the terminal/result event carries the error flag or
exit code (event shapes differ per harness — inspect the last few lines of the log once if unsure).

If no `RESULT:` line is found or the terminal event signals an error (or is missing), treat the run as `blocked` and
rely on the Phase 1.4 `gh` verification to classify the real PR state.

### 4. Post-checks — independent verification (gh is the ground truth)

Never trust the child's prose; re-derive truth:

```bash
gh pr checks <n> --repo $REPO
gh pr view <n> --repo $REPO --json state,mergeStateStatus,labels
```

Classify the outcome:
- **merged** — `state=MERGED`.
- **green-left-open** — checks green, still open, and it is a kaos-ui framework major (intentional; see merge policy).
- **superseded** — child scope-rejected: a `dependabot.yml` split PR was opened and a comment posted; original left
  open for the host to close.
- **blocked** — checks failing/timeout/child error, or any state that is none of the above.

### 5. Apply merge policy (auto-merge safe)

If the PR is **green + mergeable + still open + NOT a kaos-ui framework major + not already merged**, merge it:

```bash
gh pr merge <n> --repo $REPO --merge
```

The child already attempts this in its own Step 9; the orchestrator only acts if the PR is verifiably green but still
open (and not a held kaos-ui major). **Never** merge a kaos-ui framework major — leave it open for human review.

### 6. Record and continue

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
- **Serial** children only (shared git checkout); clean tree + `main` between runs.
- One attempt per PR; no orchestrator retry, no re-queue; every child has a `timeout`.
- **Never** load full child output into context — extract only the `RESULT:` line + error flag from the terminal
  `result` JSON object in the log; use `gh` as the ground truth.
- Fully non-interactive (autopilot); never call `ask_user`.
- Never auto-merge a kaos-ui framework major; leave it open for human review.
- Scratch under `./tmp/` (never `/tmp/`); the SQLite `todos` ledger is the durable, resumable state.
- This skill never spawns another `dependabot-fix-all`.
