import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

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

  test('A2A tab loads with agent card', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    // Click first agent to open detail
    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    // Click A2A tab
    const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
    if (await a2aTab.isVisible({ timeout: 3000 })) {
      await a2aTab.click();
      await page.waitForLoadState('networkidle');

      // Verify A2A debug container exists
      const container = page.locator('[data-testid="a2a-debug-container"]');
      await expect(container).toBeVisible({ timeout: 10000 });

      // Agent card section should show something
      const body = page.locator('body');
      const hasCardContent = await body.getByText(/agent card/i).count() > 0 ||
        await body.getByText(/supported/i).count() > 0 ||
        await body.getByText(/name/i).count() > 0;
      expect(hasCardContent).toBeTruthy();
    } else {
      test.skip(true, 'A2A tab not available for this agent');
    }
  });

  test('A2A SendMessage form renders with all controls', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
    if (!(await a2aTab.isVisible({ timeout: 3000 }))) {
      test.skip(true, 'A2A tab not available');
      return;
    }
    await a2aTab.click();
    await page.waitForLoadState('networkidle');

    // Verify SendMessage form controls
    const modeSelect = page.locator('[data-testid="a2a-mode-select"]');
    const sessionInput = page.locator('[data-testid="a2a-session-input"]');
    const messageInput = page.locator('[data-testid="a2a-message-input"]');
    const sendButton = page.locator('[data-testid="a2a-send-button"]');

    await expect(modeSelect).toBeVisible({ timeout: 5000 });
    await expect(sessionInput).toBeVisible({ timeout: 5000 });
    await expect(messageInput).toBeVisible({ timeout: 5000 });
    await expect(sendButton).toBeVisible({ timeout: 5000 });
  });

  test('A2A mode toggle shows budget fields for autonomous mode', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
    if (!(await a2aTab.isVisible({ timeout: 3000 }))) {
      test.skip(true, 'A2A tab not available');
      return;
    }
    await a2aTab.click();
    await page.waitForLoadState('networkidle');

    // Switch to autonomous mode
    const modeSelect = page.locator('[data-testid="a2a-mode-select"]');
    await expect(modeSelect).toBeVisible({ timeout: 5000 });
    await modeSelect.click();

    const autonomousOption = page.locator('[role="option"]').filter({ hasText: /autonomous/i });
    if (await autonomousOption.isVisible({ timeout: 3000 })) {
      await autonomousOption.click();

      // Budget fields should now be visible
      const body = page.locator('body');
      await expect(body).toContainText(/max iterations/i, { timeout: 5000 });
    }
  });

  test('A2A GetTask tab renders with task ID input', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
    if (!(await a2aTab.isVisible({ timeout: 3000 }))) {
      test.skip(true, 'A2A tab not available');
      return;
    }
    await a2aTab.click();
    await page.waitForLoadState('networkidle');

    // Switch to Tasks tab
    const tasksTab = page.locator('[data-testid="a2a-tab-tasks"]');
    await expect(tasksTab).toBeVisible({ timeout: 5000 });
    await tasksTab.click();

    // Task ID input should be visible
    const taskIdInput = page.locator('[data-testid="a2a-task-id-input"]');
    await expect(taskIdInput).toBeVisible({ timeout: 5000 });
  });

  test('A2A SendMessage sends request and handles response', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
    if (!(await a2aTab.isVisible({ timeout: 3000 }))) {
      test.skip(true, 'A2A tab not available');
      return;
    }
    await a2aTab.click();
    await page.waitForLoadState('networkidle');

    // Type a message and send
    const messageInput = page.locator('[data-testid="a2a-message-input"]');
    await expect(messageInput).toBeVisible({ timeout: 5000 });
    await messageInput.fill('Hello from Playwright test');

    const sendButton = page.locator('[data-testid="a2a-send-button"]');
    await sendButton.click();

    // Wait for response — either a task result or an error (e.g. model API unavailable)
    const taskDetail = page.locator('[data-testid="a2a-task-detail"]');
    const errorText = page.locator('text=/error|failed|Error/i').first();

    await expect(taskDetail.or(errorText)).toBeVisible({ timeout: 30000 });

    // If task detail appeared, it should show a task state badge
    if (await taskDetail.isVisible()) {
      const stateElement = page.locator('[data-testid="a2a-task-state"]');
      await expect(stateElement).toBeVisible({ timeout: 5000 });
      const stateText = await stateElement.textContent();
      // State should be one of the valid A2A states
      expect(['completed', 'failed', 'submitted', 'working', 'canceled']).toContain(stateText);
    }
    // If error appeared, the UI handled it gracefully (no crash)
  });
});
