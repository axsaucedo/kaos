import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe.serial('CRUD Agent with Autonomous Config', () => {
  const TEST_NAME = `test-auto-crud-${Date.now()}`;

  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver'))
        console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should CREATE agent with autonomous config', async ({ page }) => {
    // Navigate to agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    // Open create dialog
    await page.getByRole('button', { name: /create agent/i }).click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // Fill name
    await dialog.getByLabel(/name/i).first().fill(TEST_NAME);

    // Fill description (required)
    await dialog.getByLabel(/description/i).fill('Test autonomous agent for CRUD operations');

    // Fill instructions (required)
    await dialog.getByLabel(/instructions/i).fill('Monitor system health and report status periodically');

    // Select a ModelAPI
    const modelAPISelect = dialog.locator('button:has-text("Select a Model API")');
    await modelAPISelect.click();
    const firstOption = page.getByRole('option').first();
    await expect(firstOption).toBeVisible({ timeout: 3000 });
    await firstOption.click();

    // Fill model name
    const modelInput = dialog.locator('#model');
    await modelInput.scrollIntoViewIfNeeded();
    await modelInput.fill('gpt-4o-mini');

    // Scroll down to autonomous section
    const scrollArea = dialog.locator('[data-radix-scroll-area-viewport]');
    await scrollArea.evaluate(el => el.scrollTop = el.scrollHeight);

    // Fill autonomous goal (presence of goal = autonomous enabled)
    const goalInput = dialog.getByPlaceholder(/describe the autonomous goal/i);
    if (await goalInput.isVisible({ timeout: 3000 })) {
      await goalInput.fill('Monitor system health and report status');
    }

    // Submit
    await page.getByRole('button', { name: 'Create Agent' }).click();

    // Wait for dialog to close
    await expect(dialog).not.toBeVisible({ timeout: 10000 });

    // Verify agent appears in list
    await page.waitForLoadState('networkidle');
    const rows = page.locator('table tbody tr');
    const agentRow = rows.filter({ hasText: TEST_NAME });
    await expect(agentRow).toBeVisible({ timeout: 10000 });

    // Verify autonomous badge appears
    const autoText = agentRow.locator('text=Auto');
    await expect(autoText).toBeVisible({ timeout: 5000 });
  });

  test('should READ autonomous config in agent detail', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    // Click view for our agent
    const testRow = rows.filter({ hasText: TEST_NAME });
    if (await testRow.count() === 0) {
      test.skip(true, 'Test agent not found');
      return;
    }
    await testRow.getByTestId(`view-${TEST_NAME}`).click();
    await page.waitForLoadState('networkidle');

    // Overview tab should show autonomous config
    const body = page.locator('body');
    await expect(body).toContainText(/autonomous/i, { timeout: 5000 });
    await expect(body).toContainText(/monitor system health/i, { timeout: 5000 });
  });

  test('should UPDATE autonomous config', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    const testRow = rows.filter({ hasText: TEST_NAME });
    if (await testRow.count() === 0) {
      test.skip(true, 'Test agent not found');
      return;
    }

    // Click the edit button
    await testRow.getByTestId(`edit-${TEST_NAME}`).click();

    const dialog = page.locator('[role="dialog"]').last();
    await dialog.waitFor({ state: 'visible', timeout: 5000 });

    // Update autonomous goal
    const goalInput = dialog.getByPlaceholder(/describe the autonomous goal/i);
    if (await goalInput.isVisible({ timeout: 3000 })) {
      await goalInput.clear();
      await goalInput.fill('Updated: Check all services and report');
    }

    // Save
    await dialog.locator('button:has-text("Save Changes")').click();
    await expect(dialog).not.toBeVisible({ timeout: 10000 });
  });

  test('should DELETE agent with autonomous config', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    const testRow = rows.filter({ hasText: TEST_NAME });
    if (await testRow.count() === 0) {
      test.skip(true, 'Test agent not found');
      return;
    }

    // Click delete
    await testRow.getByTestId(`delete-${TEST_NAME}`).click();

    // Confirm deletion
    const confirmButton = page.getByRole('button', { name: /delete|confirm|yes/i }).last();
    await expect(confirmButton).toBeVisible({ timeout: 3000 });
    await confirmButton.click();

    // Wait for removal
    await page.waitForLoadState('networkidle');
    await expect(rows.filter({ hasText: TEST_NAME })).toHaveCount(0, { timeout: 10000 });
  });
});
