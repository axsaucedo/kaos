---
paths:
  - "kaos-ui/tests/**"
---

# KAOS-UI Testing Guidelines

Instructions for writing and running tests in KAOS-UI.

## Testing Stack

- **Vitest** for unit tests (components, hooks, stores, utilities)
- **Playwright** for end-to-end testing against a real Kubernetes cluster
- **Playwright visual tests** for deterministic screenshot regression coverage
- **CI**: `.github/workflows/kaos-ui-tests.yaml` runs build + lint + unit tests on PRs

## Directory Structure

```
kaos-ui/tests/
├── unit/                       # Vitest unit tests
│   ├── setup.ts                # Vitest test setup
│   ├── components/
│   │   └── visual-map/         # layout-engine, useVisualMapFilters
│   ├── hooks/                  # useAgentChat
│   ├── lib/                    # agent-client, status-utils
│   └── stores/                 # kubernetesStore
├── fixtures/
│   └── test-utils.ts           # Shared Playwright helpers and fixtures
├── smoke/                      # Basic app loading, cluster connectivity
├── read/                       # List/detail page tests
├── crud/                       # Create/update/delete tests
├── functional/                 # Feature workflow tests (chat, tools, visual-map)
├── integration/                # End-to-end lifecycle tests
└── visual/                     # Offline visual regression screenshots
```

## Prerequisites

```bash
npm run dev              # UI at http://localhost:8081
kaos ui --no-browser     # Proxy at http://localhost:8010
# KIND cluster with KAOS resources in kaos-hierarchy namespace
```

## Running Tests

### Unit Tests (Vitest)
```bash
npm run test:unit                          # Run all unit tests
npx vitest run tests/unit/lib/             # Run specific directory
npx vitest run --reporter=verbose          # Verbose output
npx vitest                                 # Watch mode
```

### E2E Tests (Playwright)
```bash
npm run test:e2e                           # All tests
npm run test:e2e -- tests/crud/            # CRUD tests only
npm run test:e2e -- --headed               # Visible browser
npm run test:e2e:ui                        # Interactive UI mode
npm run test:e2e -- -g "should CREATE"     # By test name
```

### Visual Tests (Playwright)
```bash
npm run test:visual                        # Verify committed screenshots
npm run test:visual:update                 # Update screenshots for intentional UI changes
npm run test:visual:ci                     # CI command
```

Visual-test details live in `kaos-ui-visual-testing.md`. Keep snapshots committed, keep failure artifacts uncommitted, and explain intentional screenshot updates in the PR.

## Writing Tests

### Unit Tests (Vitest)

```typescript
import { describe, it, expect, vi } from 'vitest';
import { someFunction } from '@/lib/status-utils';

describe('someFunction', () => {
  it('should return expected value', () => {
    expect(someFunction('input')).toBe('expected');
  });
});
```

Unit test files use `.test.ts` extension and live in `tests/unit/` mirroring the `src/` structure.

### E2E Tests (Playwright)

```typescript
import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Feature', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should do something', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await expect(page.getByText('Agent List')).toBeVisible();
  });
});
```

## CRUD Test Pattern

```typescript
test.describe.serial('CRUD Agent', () => {
  const TEST_NAME = `test-agent-${Date.now()}`;

  test('should CREATE', async ({ page }) => {
    // Navigate, fill form, submit
  });
  test('should UPDATE', async ({ page }) => { /* ... */ });
  test('should DELETE', async ({ page }) => { /* ... */ });
});
```

## Best Practices

1. **Semantic selectors**: `page.getByRole('button', { name: 'Save' })`
2. **data-testid for complex elements**: `page.getByTestId('agent-card-my-agent')`
3. **Proper waits**: `page.waitForLoadState('networkidle')`, `expect(...).toBeVisible()`
4. **Unique resource names**: `test-{resource}-${Date.now()}`
5. **Error checks**: Verify no `Something went wrong` or `TypeError` on page

## Debugging

```bash
npm run test:e2e -- --headed --debug   # Headed debug mode
npm run test:e2e -- --trace on         # Trace recording
npx playwright show-trace trace.zip    # View traces
```

Screenshots auto-captured on failure in `test-results/`.

## CI Integration

The `.github/workflows/kaos-ui-tests.yaml` workflow runs on PRs touching `kaos-ui/`:
- **Build + Lint + Unit**: `npm run build`, `npm run lint`, `npm run test:unit`
- **Visual Tests**: `npm run test:visual:ci`
- Triggered on PRs and pushes to main
