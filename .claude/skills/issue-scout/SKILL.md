---
name: issue-scout
description: Scan the KAOS repo through one rotating research lens and file at most one high-quality GitHub issue. Use this skill when asked to run /issue-scout (no arguments), typically from a daily scheduled routine. Picks the lens from the day of week, gathers evidence, checks the candidate against every existing open and closed issue, and files a normal issue only if it clears a strict quality bar — otherwise it files nothing and says so. Never pauses for user input.
allowed-tools: shell
---

# Issue Scout

Find one thing worth doing in KAOS, prove it with evidence, and file it as a normal GitHub issue. Invoked as `/issue-scout` (no arguments), usually by a daily routine.

## Core principles (do not violate)

- **Autopilot — never pause.** No interactive prompts. Every decision is resolved here.
- **At most one issue per run.** Never file two. Ranking a shortlist down to one is the job.
- **Filing nothing is a success.** On a day with no strong candidate, file nothing and report why. A weak issue costs more than an empty day.
- **Evidence or it doesn't exist.** Every claim cites a real `file:line` in this repo or a real upstream URL. Never file something you inferred but did not open.
- **Stateless.** The lens comes from the date, dedupe comes from GitHub. Nothing to persist between runs.

---

## Step 1 — Preflight

```bash
mkdir -p ./tmp && touch ./tmp/null
gh auth status                       # must succeed
```

If `gh auth status` fails, stop and report — there is no point scanning if the result cannot be filed.

The repo is `axsaucedo/kaos`. This skill never commits, never branches, and never edits tracked files; its only write to the outside world is `gh issue create` in Step 6.

## Step 2 — Load the dedupe corpus

```bash
gh issue list --repo axsaucedo/kaos --state all --limit 300 \
  --json number,title,state,labels > ./tmp/scout-issues.json
```

Read the titles. **Closed issues count**: something closed as wontfix or already-done must never be re-proposed. Only pull a body (`gh issue view <n>`) later, in Step 5, and only for the two or three issues closest to your candidate.

## Step 3 — Pick today's lens

```bash
date +%u    # 1=Mon .. 7=Sun
```

Lens = `((day - 1) % 5)`, indexed from 0 below. This rotation is the only thing stopping the scan from re-finding its favourite problem every morning, so use the lens you get — do not swap to one that feels more promising.

**0 — Code health.** Debt already visible in the tree.
```bash
grep -rn "TODO\|FIXME\|HACK\|XXX" --include=*.go --include=*.py --include=*.ts --include=*.tsx . | grep -v node_modules | head -50
grep -rn "@pytest.mark.skip\|t.Skip(\|it.skip\|describe.skip" --include=*.py --include=*.go --include=*.ts . | grep -v node_modules | head -30
```
Also look for error paths that swallow (`except Exception: pass`, `if err != nil { return nil }`) and logic duplicated across the Go and Python planes.

**1 — Correctness risk.** Where the system can be wrong rather than merely ugly.
Read `operator/api/v1alpha1/*_types.go` and compare the CRD surface against `operator/controllers/*_controller.go`: fields with no validation markers, spec fields no reconciler reads, status conditions never set, requeue paths that can spin. Then check `operator/tests/e2e/` for CRD behaviour with no e2e coverage.

**2 — Docs/DX drift.** Where the docs and the code disagree.
Compare `docs/` and `.github/instructions/*` against reality: CLI flags in `kaos-cli/kaos_cli/` versus documented ones, CRD fields versus documented ones, examples in `operator/config/samples/` that no longer apply cleanly. Drift is worth filing only when it would actively mislead a user, not when it is merely incomplete.

**3 — Ecosystem.** What changed outside the repo that KAOS should react to.
Check current pins (`operator/go.mod`, `pydantic-ai-server/pyproject.toml`, `kaos-memory/pyproject.toml`, `kaos-ui/package.json`), then research upstream releases and deprecations for the ones carrying design weight — pydantic-ai, the MCP spec, kubebuilder/controller-runtime, Envoy Gateway, Mem0. Dependabot already handles version bumps, so a bump alone is never the issue; the issue is a capability or deprecation that changes what KAOS should do.

**4 — Roadmap gaps.** The next concrete slice of work already on the board.
Read the open `feat:` epics from `./tmp/scout-issues.json`, pick one, and propose the specific next PR-sized slice that unblocks it. The slice must be independently useful — not "phase 1 of 6" with no standalone value.

## Step 4 — Shortlist

Produce three to five candidates from the lens, each with its evidence, and write them to `./tmp/scout-candidates.md` so ranking works off a written list rather than memory. Rank by severity of the real-world consequence, then how self-contained the fix is, then how well the evidence holds up.

## Step 5 — Apply the bar to the top candidate

Every one of these must hold. Walk down the list; the first failure kills the candidate and you move to the next one on the shortlist.

- **Evidence is real.** Re-open each cited file at the cited line and confirm it says what the candidate claims. Cited upstream URLs must have actually been fetched. If a citation does not hold up, drop the candidate — do not soften the claim to fit.
- **Not a duplicate.** `gh issue view <n>` the two or three nearest issues from the corpus and read them. Overlapping scope with an open issue, or with an issue closed as wontfix, is a duplicate. Being a *strict subset* of an open epic is not a duplicate when you are proposing its concrete next slice.
- **One PR.** A focused change a single person lands in one PR. If it needs a design doc first, then the issue is the design doc, scoped that way.
- **Testable.** You can write acceptance criteria a reviewer could check objectively.
- **Not already automated.** Not a lint/format nit, not a version bump, not something CI or Dependabot already catches.

If no candidate clears the bar, skip to Step 7.

## Step 6 — File it

Write the body to `./tmp/scout-issue.md`:

```markdown
## Problem
<what is wrong, with file links: https://github.com/axsaucedo/kaos/blob/main/<path>#L<n>>

## Why now
<the consequence, or the upstream change that forces it>

## Proposed approach
<the shape of the change; name the files>

## Acceptance criteria
- [ ] <objectively checkable>

## Out of scope
<the adjacent things this deliberately does not touch>
```

Title uses the repo's conventional style — `feat(scope):`, `fix(scope):`, `bug:`, `docs:` — matching the existing issue list. Label with the component it belongs to and nothing else: `CRD`, `Data Plane`, `Control Plane`, `CLI`, `frontend`, `documentation`, `bug`, or `enhancement`. Do **not** apply `automated`; that label belongs to release PRs.

```bash
gh issue create --repo axsaucedo/kaos \
  --title "<title>" --body-file ./tmp/scout-issue.md --label "<label>"
```

## Step 7 — Report

Two to five lines to stdout, no file:

- Lens used.
- Issue filed, with number and URL — or `no issue filed`.
- When nothing was filed: the strongest candidate considered and which bar item it failed. That is what tells you whether the lens is exhausted or the bar is miscalibrated.
