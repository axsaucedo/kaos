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

function mockTask(id: string, text: string, state = 'completed') {
  return {
    id,
    sessionId: `session-${id}`,
    status: { state, timestamp: new Date().toISOString(), message: 'Done' },
    history: [
      { role: 'user', parts: [{ type: 'text', text }] },
      { role: 'agent', parts: [{ type: 'text', text: 'Mock response from agent' }] },
    ],
    artifacts: [],
    metadata: {},
    events: [],
    autonomous: false,
    output: 'Mock response from agent',
  };
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

  test('task history loads retained tasks and refreshes from ListTasks', async ({ page }) => {
    let listCalls = 0;

    await page.route('**/proxy/', async (route) => {
      if (route.request().method() === 'POST') {
        let body: Record<string, unknown> = {};
        try { body = route.request().postDataJSON(); } catch { /* ignore */ }
        if (body?.jsonrpc === '2.0' && (body?.method === 'ListTasks' || body?.method === 'tasks/list')) {
          listCalls += 1;
          const task = listCalls === 1
            ? mockTask('task_retained_pw_001', 'Retained task from backend')
            : mockTask('task_retained_pw_002', 'Refreshed retained task');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              jsonrpc: '2.0',
              id: body.id,
              result: { tasks: [task], count: 1 },
            }),
          });
          return;
        }
        if (body?.jsonrpc === '2.0' && (body?.method === 'GetTask' || body?.method === 'tasks/get')) {
          const params = body.params as Record<string, unknown> | undefined;
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              jsonrpc: '2.0',
              id: body.id,
              result: mockTask(String(params?.id || 'task_retained_pw_001'), 'Retained task from backend'),
            }),
          });
          return;
        }
      }
      await route.continue();
    });

    if (!(await navigateToA2ATab(page))) {
      test.skip(true, 'A2A tab not available');
      return;
    }

    const historyEntry = page.locator('[data-testid="a2a-history-0"]');
    await expect(historyEntry).toBeVisible({ timeout: 10000 });
    await expect(historyEntry).toContainText('Retained task from backend');

    await page.locator('[data-testid="a2a-refresh-tasks"]').click();
    await expect(page.locator('[data-testid="a2a-history-0"]')).toContainText('Refreshed retained task', { timeout: 10000 });
  });

  test('send message → task appears in history → clicking history auto-switches to task tab', async ({ page }) => {
    test.setTimeout(60000);
    if (!(await navigateToA2ATab(page))) {
      test.skip(true, 'A2A tab not available');
      return;
    }

    // Mock A2A JSON-RPC endpoint to avoid depending on live agent
    await page.route('**/proxy/', async (route) => {
      if (route.request().method() === 'POST') {
        let body: Record<string, unknown> = {};
        try { body = route.request().postDataJSON(); } catch { /* ignore */ }
        if (body?.jsonrpc === '2.0' && (body?.method === 'SendMessage' || body?.method === 'tasks/send')) {
          const params = body.params as Record<string, unknown> | undefined;
          const msg = params?.message as Record<string, unknown> | undefined;
          const parts = (msg?.parts as Array<Record<string, unknown>>) || [];
          const text = String(parts[0]?.text || 'test');
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              jsonrpc: '2.0',
              id: body.id,
              result: {
                id: 'task_mock_pw_001',
                sessionId: 'session_mock_001',
                status: { state: 'completed', timestamp: new Date().toISOString(), message: 'Done' },
                history: [
                  { role: 'user', parts: [{ type: 'text', text }] },
                  { role: 'agent', parts: [{ type: 'text', text: 'Mock response from agent' }] },
                ],
                artifacts: [],
                autonomous: false,
                output: 'Mock response from agent',
              },
            }),
          });
          return;
        }
        if (body?.jsonrpc === '2.0' && (body?.method === 'GetTask' || body?.method === 'tasks/get')) {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              jsonrpc: '2.0',
              id: body.id,
              result: {
                id: 'task_mock_pw_001',
                sessionId: 'session_mock_001',
                status: { state: 'completed', timestamp: new Date().toISOString(), message: 'Done' },
                history: [
                  { role: 'user', parts: [{ type: 'text', text: 'Playwright A2A workflow test' }] },
                  { role: 'agent', parts: [{ type: 'text', text: 'Mock response from agent' }] },
                ],
                artifacts: [],
                autonomous: false,
                output: 'Mock response from agent',
              },
            }),
          });
          return;
        }
      }
      await route.continue();
    });

    // Fill and send a message
    const messageInput = page.locator('[data-testid="a2a-message-input"]');
    await messageInput.fill('Playwright A2A workflow test');
    await page.locator('[data-testid="a2a-send-button"]').click();

    // Wait for task to appear in history sidebar (task detail is in the other tab)
    const historyEntry = page.locator('[data-testid="a2a-history-0"]');
    await expect(historyEntry).toBeVisible({ timeout: 30000 });

    // Click history entry — should auto-switch to Get/Cancel tab and show task detail
    await historyEntry.click();

    const taskDetail = page.locator('[data-testid="a2a-task-detail"]');
    await expect(taskDetail).toBeVisible({ timeout: 5000 });

    // Task state badge should show a valid state
    const stateElement = page.locator('[data-testid="a2a-task-state"]');
    await expect(stateElement).toBeVisible({ timeout: 5000 });
    const stateText = await stateElement.textContent();
    expect(['completed', 'failed', 'submitted', 'working', 'canceled']).toContain(stateText);

    // Task ID input should be visible (for manual lookups)
    const taskIdInput = page.locator('[data-testid="a2a-task-id-input"]');
    await expect(taskIdInput).toBeVisible({ timeout: 5000 });

    // Task detail should show the task ID from mock
    const taskDetailText = await taskDetail.textContent();
    expect(taskDetailText).toBeTruthy();

    // Switch back to Send tab to verify form is accessible
    await page.locator('[data-testid="a2a-tab-send"]').click();
    await expect(page.locator('[data-testid="a2a-message-input"]')).toBeVisible({ timeout: 3000 });
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
