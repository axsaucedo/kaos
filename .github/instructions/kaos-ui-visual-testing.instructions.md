---
applyTo: "{kaos-ui/tests/visual/**,kaos-ui/playwright.visual.config.ts,kaos-ui/src/**/*.tsx,kaos-ui/src/index.css,kaos-ui/package.json,.github/workflows/kaos-ui-tests.yaml}"
---

# KAOS UI Visual Testing

Keep visual-test guidance functional, simple, and concise.

## Purpose

- Visual tests catch pixel-level UI regressions in layout, theme, Tailwind output, dialogs, forms, tabs, and major screen states.
- They complement unit tests and live KIND E2E tests; they do not replace either.

## Model

- Visual specs live in `kaos-ui/tests/visual/**`.
- The harness must be deterministic and offline: mock Kubernetes/proxy/A2A/MCP/model/memory APIs in fixtures.
- Do not depend on KIND, `kaos ui`, real time/randomness, external fonts, or operator readiness.
- Keep `kaos-ui/playwright.config.ts` ignoring `**/visual/**` so live E2E shards do not run visual specs.

## Snapshots and artifacts

- Committed baselines live under `kaos-ui/tests/visual/__screenshots__/`.
- Failure artifacts live in `kaos-ui/test-results/` and `kaos-ui/playwright-report/visual/`; do not commit them.
- Use `./tmp/...` for local analysis output; do not use `/tmp`.

## Commands

```bash
cd kaos-ui
npm run test:visual        # verify snapshots
npm run test:visual:update # update snapshots after intentional UI changes
npm run test:visual:ci     # CI command
```

## Intentional UI changes

- If UI intentionally changes, such as adding a visible form field, update affected snapshots in the same PR.
- Do not weaken thresholds, delete screenshots, or skip visual tests to hide expected diffs.
- Add a PR comment that lists changed snapshots, why the diff is intentional, commands run, and CI status.

## Failures

- Treat visual failures as regressions until reviewed.
- Inspect expected/actual/diff images from `test-results/` or the CI artifacts.
- Fix source/theme/test determinism first; update snapshots only when the new UI is intended.
- CI should comment on PR visual failures with artifact links and local debug/update commands.

## CI policy

- Run visual tests for every `kaos-ui/**` PR through the `Visual Tests` job.
- Keep visual checks blocking for UI PRs.
