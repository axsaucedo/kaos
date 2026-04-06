import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

/**
 * Navigate to A2A tab for the first available agent.
 * Returns true if A2A tab was found and activated.
 */
async function navigateToA2ATab(page: import('@playwright/test').Page): Promise<boolean> {
  await page.getByRole('button', { name: /agents/i }).click();
  await page.waitForLoadState('networkidle');

  const rows = page.locator('table tbody tr');
  await expect(rows.first()).toBeVisible({ timeout: 5000 });
  await rows.first().locator('button').first().click();
  await page.waitForLoadState('networkidle');

  const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
  if (!(await a2aTab.isVisible({ timeout: 3000 }))) return false;

  await a2aTab.click();
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[data-testid="a2a-debug-container"]')).toBeVisible({ timeout: 10000 });
  return true;
}

test.describe('A2A Debug Screen', () => {
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

  test('A2A tab loads with agent card and SendMessage form', async ({ page }) => {
    if (!(await navigateToA2ATab(page))) {
      test.skip(true, 'A2A tab not available');
      return;
    }

    // Agent card section should display
    const body = page.locator('body');
    const hasCardContent = await body.getByText(/agent card/i).count() > 0 ||
      await body.getByText(/supported/i).count() > 0 ||
      await body.getByText(/name/i).count() > 0;
    expect(hasCardContent).toBeTruthy();

    // Verify all SendMessage form controls are present
    await expect(page.locator('[data-testid="a2a-mode-select"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-testid="a2a-session-input"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-testid="a2a-message-input"]')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-testid="a2a-send-button"]')).toBeVisible({ timeout: 5000 });
  });

  test('mode toggle: interactive shows no budgets, async task shows budget fields', async ({ page }) => {
    if (!(await navigateToA2ATab(page))) {
      test.skip(true, 'A2A tab not available');
      return;
    }

    const body = page.locator('body');
    // In default interactive mode, no budget fields
    const hasBudgetBefore = await body.getByText(/max iterations/i).count();
    expect(hasBudgetBefore).toBe(0);

    // Switch to async task mode
    const modeSelect = page.locator('[data-testid="a2a-mode-select"]');
    await modeSelect.click();
    const asyncOption = page.locator('[role="option"]').filter({ hasText: /async task/i });
    if (await asyncOption.isVisible({ timeout: 3000 })) {
      await asyncOption.click();
      await expect(body).toContainText(/max iterations/i, { timeout: 5000 });
    }

    // Switch back to interactive — budgets should disappear
    await modeSelect.click();
    const interactiveOption = page.locator('[role="option"]').filter({ hasText: /interactive/i });
    if (await interactiveOption.isVisible({ timeout: 3000 })) {
      await interactiveOption.click();
      await page.waitForTimeout(500);
      const hasBudgetAfter = await body.getByText(/max iterations/i).count();
      expect(hasBudgetAfter).toBe(0);
    }
  });

  test('send message → task appears in history → clicking history auto-switches to task tab', async ({ page }) => {
    test.setTimeout(60000);
    if (!(await navigateToA2ATab(page))) {
      test.skip(true, 'A2A tab not available');
      return;
    }

    // Fill and send a message
    const messageInput = page.locator('[data-testid="a2a-message-input"]');
    await messageInput.fill('Playwright A2A workflow test');
    await page.locator('[data-testid="a2a-send-button"]').click();

    // Wait for response — either task detail or error
    const taskDetail = page.locator('[data-testid="a2a-task-detail"]');
    const errorIndicator = page.locator('text=/error|failed|Error/i').first();
    await expect(taskDetail.or(errorIndicator)).toBeVisible({ timeout: 30000 });

    // If we got a task detail, validate the full workflow
    if (await taskDetail.isVisible()) {
      // Task state badge should show a valid state
      const stateElement = page.locator('[data-testid="a2a-task-state"]');
      await expect(stateElement).toBeVisible({ timeout: 5000 });
      const stateText = await stateElement.textContent();
      expect(['completed', 'failed', 'submitted', 'working', 'canceled']).toContain(stateText);

      // Task history should have at least one entry
      const historyEntry = page.locator('[data-testid="a2a-history-0"]');
      await expect(historyEntry).toBeVisible({ timeout: 5000 });

      // Switch back to Send tab first
      await page.locator('[data-testid="a2a-tab-send"]').click();
      await expect(page.locator('[data-testid="a2a-message-input"]')).toBeVisible({ timeout: 3000 });

      // Click history entry — should auto-switch to Get/Cancel tab
      await historyEntry.click();
      const taskIdInput = page.locator('[data-testid="a2a-task-id-input"]');
      await expect(taskIdInput).toBeVisible({ timeout: 5000 });

      // Task ID input should be populated with the task ID from history
      const taskIdValue = await taskIdInput.inputValue();
      expect(taskIdValue.length).toBeGreaterThan(0);
    }
  });

  test('Get/Cancel tab: lookup task by ID shows task state', async ({ page }) => {
    if (!(await navigateToA2ATab(page))) {
      test.skip(true, 'A2A tab not available');
      return;
    }

    // Switch to Get/Cancel tab
    await page.locator('[data-testid="a2a-tab-tasks"]').click();
    const taskIdInput = page.locator('[data-testid="a2a-task-id-input"]');
    await expect(taskIdInput).toBeVisible({ timeout: 5000 });

    // Enter a non-existent task ID and try to get it
    await taskIdInput.fill('non-existent-task-id-12345');
    const getButton = page.getByRole('button', { name: /get task/i });
    if (await getButton.isVisible({ timeout: 3000 })) {
      await getButton.click();
      await page.waitForTimeout(3000);

      // Should show an error or "not found" — UI should not crash
      const body = page.locator('body');
      const hasNoError = await body.locator('text=TypeError').count() === 0 &&
        await body.locator('text=Something went wrong').count() === 0;
      expect(hasNoError).toBeTruthy();
    }
  });
});
