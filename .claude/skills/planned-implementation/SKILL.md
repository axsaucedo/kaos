---
name: planned-implementation
description: Plan and execute complex KAOS implementation work with staged context gathering, backend/UI synthesis, validation, PR/CI checks, and REPORT.md PR-comment output.
allowed-tools: shell
---

# Planned Implementation

Use this skill for complex KAOS changes that span multiple domains, especially backend plus UI work. The goal is to keep working context focused by gathering domain knowledge in staged passes, documenting only the relevant findings, then executing numbered tasks one by one with validation and commits.

IMPORTANT INSRTUCTIONS: This is quite a comprehensive request, so please ensure that before starting you put together a comprehensive plan to move forward, and a design plan on how this will fit the existing codebase. Create a set of tasks from the TODOs outlined below by number, and make sure you carry them out one by one without skipping any, each of them should ensure the tests are validated and passing, and committed with using commits using "comprehensive commit" style with succint and functional descriptions each individual task is done. Ensure that all tests pass. You have access to github CI, so whenever you create a set of commits, make sure to push to a PR (if not there create one) and validate that they all run correctly; if any major refactors make sure that you run the python and golang tests locally, and you have a KIND cluster available so run 1-3 tests locally before pushing to run the end to end tests in the CI; prefer to run the complete set of tests in the CI github actions, but if you see many failing again run 1-3 locally to validate before; be efficient when it comes to testing.  We are still in alpha so breaking changes can be done and migration does not need to be documented.

## Ground rules

- Do not start implementation before a written plan exists and the user has approved it.
- Use focused context phases. Prefer subagents for broad research; otherwise gather one domain at a time and write compact notes before moving to the next domain.
- Use `./tmp` for scratch files and suppressed output. Do not use `/tmp` unless external-host access is truly required.
- Create or overwrite `REPORT.md` at the end, but never commit it. Post its contents as a PR comment.
- Commit each numbered TODO separately with a succinct conventional commit message and the required co-author trailer.
- Do not skip validation for a TODO before committing it. If validation cannot run locally, document why in `REPORT.md` and rely on PR CI.
- Prefer real local validation when the host already has Docker, Kubernetes, KAOS, UI dev servers, or proxy configuration running. Detect and reuse that setup before falling back to mocked tests or CI-only validation.

## Phase 0 - Scope and setup

1. Restate the user request in one paragraph.
2. Identify touched domains: Python backend, Go operator, UI, docs, CLI, workflows, or skills.
3. Create scratch space:

```bash
mkdir -p ./tmp
touch ./tmp/null
```

4. Check repository state before editing:

```bash
git --no-pager status --short --branch
```

Stop and ask the user if existing unrelated changes conflict with the requested work.

5. Detect reusable local runtime configuration and record what is available:

```bash
{
  echo "## Local validation environment"
  command -v docker >/dev/null && docker ps --format 'docker: {{.Names}} {{.Status}}' || true
  command -v kubectl >/dev/null && kubectl config current-context 2>./tmp/null || true
  command -v kubectl >/dev/null && kubectl cluster-info 2>./tmp/null || true
  command -v kaos >/dev/null && kaos version 2>./tmp/null || true
  curl -sS -o ./tmp/null -w 'ui:%{http_code}\n' http://localhost:8080/ || true
  curl -sS -o ./tmp/null -w 'ui-alt:%{http_code}\n' http://localhost:8081/ || true
  curl -sS -o ./tmp/null -w 'proxy:%{http_code}\n' http://localhost:8010/ || true
} | tee ./tmp/local-validation-context.txt
```

If the user says a local KAOS cluster is running, treat the local runtime as the primary E2E validation target. Do not skip local E2E solely because CI will run later.

## Phase 1 - Backend context

Read only backend-relevant instructions, docs, source, and tests first. Use this mapping:

- `pydantic-ai-server/**` -> `.claude/rules/python.md`
- `operator/**/*.go` -> `.claude/rules/operator.md`
- `operator/tests/**` -> `.claude/rules/e2e.md`
- `kaos-cli/**` -> Python instructions plus CLI docs/tests

Capture:

- Entry points and public APIs.
- Existing data models and serialization contracts.
- Tests that currently cover the behavior.
- Validation commands and any known gotchas.
- Risks, migration notes, and compatibility decisions.

Do not start UI research until backend notes are complete.

## Phase 2 - UI context

Read only UI-relevant instructions, source, and tests:

- `.claude/rules/kaos-ui.md`
- `.claude/rules/kaos-ui-testing.md`
- `.claude/rules/kaos-ui-components.md` when components are touched
- `.claude/rules/kaos-ui-kubernetes-types.md` when Kubernetes/CRD types are touched

Capture:

- Component/state ownership.
- Client/API boundaries.
- Existing UX patterns and test selectors.
- Unit, functional, and Playwright validation paths.
- Manual validation needs.

Do not start cross-domain design until UI notes are complete.

## Phase 3 - Docs, skills, and workflow context

Read docs and repo instructions that describe the public surface or workflow being changed:

- `CLAUDE.md`
- `.claude/skills/*/SKILL.md` for skill conventions
- `.claude/rules/docs.md` for docs changes
- Relevant pages under `docs/`

Capture:

- Public documentation that must change with the implementation.
- Instruction files that should stay in sync.
- Skill or workflow conventions to preserve.

## Phase 4 - Cross-domain synthesis

Create a compact design that answers:

- What contract connects backend and UI?
- What behavior is intentionally changed?
- What defaults keep the implementation simple?
- What tests prove the contract end-to-end?
- What is explicitly out of scope?

Prefer the smallest complete design that fits existing code. KAOS is alpha, so breaking changes can be accepted when useful, but do not break unrelated behavior casually.

## Phase 5 - Plan and TODOs

Write a plan with:

- Problem statement.
- Current-state summary by domain.
- Design plan.
- Numbered TODOs.
- Validation per TODO.
- Commit and PR/CI strategy.
- `REPORT.md` requirements.

Reflect the TODOs into any available task tracker and keep status updated as work progresses.

## Phase 6 - Execute one TODO at a time

For each numbered TODO:

1. Mark the TODO in progress.
2. Make only the changes needed for that TODO.
3. Run targeted validation for that TODO.
4. Fix failures before moving on.
5. Commit the completed TODO.
6. Mark the TODO done.

Do not batch unrelated TODOs into one commit.

## Phase 7 - Validation and PR/CI

Use targeted local validation first, then PR CI for broader coverage.

Before running E2E, inspect `./tmp/local-validation-context.txt` and reuse available configuration:

- If `kubectl cluster-info` works, use the current kube context; do not create a new KIND cluster unless tests require isolation.
- If `kaos ui --no-browser` or another proxy is already serving on `localhost:8010`, use that proxy.
- If the UI is already serving on `localhost:8080` or `localhost:8081`, use the matching Playwright base URL or config instead of starting a duplicate server.
- If Docker is running and a KAOS cluster is installed, prefer a small real-browser Playwright path through the local UI and proxy for UI changes.
- If the proxy or UI is missing, start only the missing process, capture logs under `./tmp`, and stop only processes you started.
- Keep all temporary logs/config under `./tmp`.

Common commands:

```bash
# Python backend
cd pydantic-ai-server && source .venv/bin/activate
python -m pytest tests/ -v
make lint

# UI
cd kaos-ui
npm run test:unit
npm run lint
npm run build
npm run test:e2e -- tests/functional/

# Operator, only when operator code changes
cd operator
make generate manifests
make test-unit
```

For end-to-end coverage, prefer GitHub Actions on a PR. If many CI failures occur, reproduce 1-3 relevant tests locally before pushing follow-up fixes.

For UI work against an existing local KAOS cluster, run at least one targeted Playwright test against the real local setup when available, for example:

```bash
cd kaos-ui
KAOS_UI_BASE_URL=http://localhost:8080 \
KAOS_PROXY_URL=http://localhost:8010 \
npm run test:e2e -- tests/functional/<relevant-test>.spec.ts
```

If the repo's Playwright config does not read those environment variables, either use the default ports expected by the config or pass an equivalent Playwright `--config`/environment setup already used in the repo. Record the exact command and observed result in `REPORT.md`.

## Phase 8 - REPORT.md and PR comment

Create or overwrite `REPORT.md` in the repository root with:

- Original request and numbered TODOs.
- Implementation status for each TODO.
- Commits created.
- Validation run locally.
- CI/PR status.
- Risks, follow-ups, and anything incomplete.

Do not commit `REPORT.md`. Post its contents as a PR comment:

```bash
gh pr comment <pr-number> --body-file REPORT.md
```
