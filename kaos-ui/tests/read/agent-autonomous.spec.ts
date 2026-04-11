import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Agent Autonomous Badges & Indicators', () => {
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

  test('autonomous agents show Auto badge, non-autonomous agents do not', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    const allRows = await rows.count();
    let autoCount = 0;
    let nonAutoCount = 0;

    for (let i = 0; i < allRows; i++) {
      const rowText = await rows.nth(i).textContent();
      if (rowText && rowText.includes('Auto')) {
        autoCount++;
      } else {
        nonAutoCount++;
      }
    }

    // At least one autonomous agent should exist
    if (autoCount === 0) {
      test.skip(true, 'No autonomous agents found in cluster');
      return;
    }

    expect(autoCount).toBeGreaterThan(0);
    // There should also be non-autonomous agents
    expect(nonAutoCount).toBeGreaterThan(0);
  });

  test('autonomous agent detail shows goal, budgets, and autonomous section', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    // Find an autonomous agent by looking for the Auto badge
    const autoBadge = page.locator('text=Auto').first();
    if (await autoBadge.count() === 0) {
      test.skip(true, 'No autonomous agents found in cluster');
      return;
    }

    // Click the view button for the autonomous agent
    const viewButton = page.getByTestId('view-test-auto-agent');
    if (await viewButton.isVisible({ timeout: 3000 })) {
      await viewButton.click();
    } else {
      // Fallback: find auto row and click view button
      const autoRow = page.locator('table tbody tr').filter({ hasText: 'Auto' }).first();
      const buttons = autoRow.locator('[data-testid^="view-"]');
      await buttons.first().click();
    }
    await page.waitForLoadState('networkidle');

    // Overview tab should show autonomous config section
    const body = page.locator('body');
    await expect(body).toContainText(/autonomous/i, { timeout: 5000 });

    // Should show the autonomous goal text
    const hasGoal = await body.getByText(/goal/i).count() > 0 ||
      await body.getByText(/monitor|check|report/i).count() > 0;
    expect(hasGoal).toBeTruthy();

    // Navigate through tabs to verify agent has A2A tab
    const a2aTab = page.locator('[data-testid="tab-a2a"]').or(page.getByRole('tab', { name: /a2a/i }));
    if (await a2aTab.isVisible({ timeout: 3000 })) {
      await a2aTab.click();
      await page.waitForLoadState('networkidle');
      // A2A debug container should load
      await expect(page.locator('[data-testid="a2a-debug-container"]')).toBeVisible({ timeout: 10000 });
    }
  });

  test('visual map renders agent nodes without edge text labels', async ({ page }) => {
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');

    const flowContainer = page.locator('.react-flow');
    await expect(flowContainer).toBeVisible({ timeout: 5000 });

    // Visual map should render nodes
    const nodes = page.locator('.react-flow__node');
    await expect(nodes.first()).toBeVisible({ timeout: 5000 });
    const nodeCount = await nodes.count();
    expect(nodeCount).toBeGreaterThan(0);

    // Edges should exist but should NOT have text labels
    const edges = page.locator('.react-flow__edge');
    const edgeCount = await edges.count();

    if (edgeCount > 0) {
      // Edge label elements should not contain text like "model", "a2a", "tools"
      const edgeLabels = page.locator('.react-flow__edge-textwrapper');
      const labelCount = await edgeLabels.count();
      // After our fix, there should be no text labels on edges
      expect(labelCount).toBe(0);
    }
  });
});
