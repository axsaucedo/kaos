---
applyTo: "kaos-ui/tests/**"
---

# KAOS-UI Testing Guidelines

Instructions for writing and running Playwright tests in KAOS-UI.

## Testing Stack

- **Playwright** for end-to-end testing
- Tests run against a real Kubernetes cluster via the KAOS proxy

## Directory Structure

```
kaos-ui/tests/
├── fixtures/
│   └── test-utils.ts           # Shared helpers and fixtures
├── smoke/                      # Basic app loading, cluster connectivity
├── read/                       # List/detail page tests
├── crud/                       # Create/update/delete tests
├── functional/                 # Feature workflow tests (chat, tools)
└── integration/                # End-to-end lifecycle tests
```

## Prerequisites

```bash
npm run dev              # UI at http://localhost:8081
kaos ui --no-browser     # Proxy at http://localhost:8010
# KIND cluster with KAOS resources in kaos-hierarchy namespace
```

## Running Tests

```bash
npm run test:e2e                           # All tests
npm run test:e2e -- tests/crud/            # CRUD tests only
npm run test:e2e -- --headed               # Visible browser
npm run test:e2e:ui                        # Interactive UI mode
npm run test:e2e -- -g "should CREATE"     # By test name
```

## Writing Tests

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
