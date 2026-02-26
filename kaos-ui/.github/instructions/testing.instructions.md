# Testing Guidelines

Instructions for writing and running tests in KAOS-UI.

## Testing Stack

- **Playwright** for end-to-end testing
- Tests run against a real Kubernetes cluster via the KAOS proxy

## Directory Structure

```
tests/
├── fixtures/
│   └── test-utils.ts           # Shared helpers and fixtures
├── smoke/
│   ├── app-loads.spec.ts       # Basic app loading
│   └── cluster-connection.spec.ts  # Cluster connectivity
├── read/
│   ├── modelapi.spec.ts        # ModelAPI list/detail
│   ├── agent.spec.ts           # Agent list/detail
│   └── mcpserver.spec.ts       # MCPServer list/detail
├── crud/
│   ├── modelapi.spec.ts        # ModelAPI create/update/delete
│   ├── agent.spec.ts           # Agent create/update/delete
│   └── mcpserver.spec.ts       # MCPServer create/update/delete
├── functional/
│   ├── agent-chat.spec.ts      # Agent chat and memory
│   ├── mcpserver-tools.spec.ts # MCP tools UI
│   └── modelapi-request.spec.ts # ModelAPI diagnostics
└── integration/
    └── full-lifecycle.spec.ts  # End-to-end workflows
```

## Prerequisites

### Required Services

1. **KAOS UI Development Server**
   ```bash
   npm run dev
   # Runs at http://localhost:8081
   ```

2. **KAOS Proxy** (for cluster connection)
   ```bash
   kaos ui --no-browser
   # Runs at http://localhost:8010
   ```

3. **Kubernetes Cluster** with KAOS CRDs installed
   - Tests use the `kaos-hierarchy` namespace by default
   - Requires existing resources for read tests

### Configuration

Tests use configuration from `tests/fixtures/test-utils.ts`:

```typescript
export const TEST_CONFIG = {
  proxyUrl: 'http://localhost:8010',
  namespace: 'kaos-hierarchy',
  baseUrl: 'http://localhost:8081',
};
```

## Running Tests

```bash
# Run all tests
npm run test:e2e

# Run specific test file
npm run test:e2e -- tests/smoke/app-loads.spec.ts

# Run specific test category
npm run test:e2e -- tests/crud/

# Run in headed mode (visible browser)
npm run test:e2e -- --headed

# Run with UI mode (interactive)
npm run test:e2e:ui

# Run specific test by name
npm run test:e2e -- -g "should CREATE"
```

## Writing Tests

### Basic Structure

```typescript
import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Feature Name', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should do something', async ({ page }) => {
    // Navigate
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    // Assert
    await expect(page.getByText('Agent List')).toBeVisible();
  });
});
```

### CRUD Test Pattern

```typescript
test.describe.serial('Create, Update, Delete Agent', () => {
  const TEST_NAME = `test-agent-${Date.now()}`;
  
  test('should CREATE', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.getByRole('button', { name: /create agent/i }).click();
    
    const dialog = page.locator('[role="dialog"]');
    await dialog.getByLabel(/name/i).fill(TEST_NAME);
    await dialog.getByLabel(/model/i).fill('gpt-4o-mini');
    
    // Select ModelAPI
    await dialog.locator('button:has-text("Select a Model API")').click();
    await page.getByRole('option').first().click();
    
    await page.getByRole('button', { name: 'Create Agent' }).click();
    await page.waitForTimeout(2000);
    
    await expect(page.locator('body')).toContainText(TEST_NAME);
  });

  test('should UPDATE', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    const row = page.locator('table tbody tr').filter({ hasText: TEST_NAME });
    await row.locator('button').nth(1).click(); // Edit button
    
    await page.getByLabel(/instructions/i).fill('Updated instructions');
    await page.getByRole('button', { name: /update/i }).click();
  });

  test('should DELETE', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    const row = page.locator('table tbody tr').filter({ hasText: TEST_NAME });
    await row.locator('button').nth(2).click(); // Delete button
    
    await page.getByRole('button', { name: /confirm|delete/i }).click();
    await page.waitForTimeout(2000);
    
    await expect(row).not.toBeVisible();
  });
});
```

## Best Practices

### 1. Use Semantic Selectors

```typescript
// Good - semantic
await page.getByRole('button', { name: 'Save' }).click();
await page.getByLabel('Model').fill('gpt-4');
await page.getByText('Overview').click();

// Avoid - fragile
await page.locator('.btn-primary').click();
await page.locator('#input-3').fill('gpt-4');
```

### 2. Add data-testid for Complex Elements

```tsx
// In component
<Card data-testid={`agent-card-${agent.metadata.name}`}>

// In test
await page.getByTestId('agent-card-my-agent').click();
```

### 3. Wait Properly

```typescript
// Wait for network
await page.waitForLoadState('networkidle');

// Wait for element
await expect(page.getByText('Success')).toBeVisible();

// Wait for dialog
await page.waitForSelector('[role="dialog"]');
```

### 4. Check for Errors

```typescript
// After navigation
const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                 await page.locator('text=TypeError').count() > 0;
expect(hasError, 'Page should not show errors').toBeFalsy();
```

### 5. Use Unique Resource Names

```typescript
const TEST_NAME = `test-modelapi-${Date.now()}`;
```

### 6. Handle Missing Resources Gracefully

```typescript
const rowCount = await testRow.count();
if (rowCount === 0) {
  console.log('Resource not found, skipping');
  test.skip();
  return;
}
```

## Debugging

### Headed Mode

```bash
npm run test:e2e -- --headed --debug
```

### Trace Viewer

```bash
npm run test:e2e -- --trace on
npx playwright show-trace trace.zip
```

### Screenshots

Auto-captured on failure. Location: `test-results/`

### Console Output

```typescript
page.on('console', msg => console.log(msg.text()));
```

## Test Categories

| Category | Purpose | When to Run |
|----------|---------|-------------|
| smoke | Basic validation | Every commit |
| read | List/detail pages | When modifying display |
| crud | Create/Update/Delete | When modifying forms |
| functional | Feature workflows | When modifying features |
| integration | End-to-end flows | Before release |

## CI/CD

Tests run on:
- Pull requests to main
- Pushes to main branch
- Release tags

See `.github/workflows/` for configuration.
