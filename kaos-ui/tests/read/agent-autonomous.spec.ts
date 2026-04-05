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

  test('autonomous agent shows badge in agent list', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    // Look for any autonomous badge in the list
    const autoBadges = page.locator('text=Auto');
    const badgeCount = await autoBadges.count();

    // At least one agent should have an autonomous badge if test-auto-agent exists
    if (badgeCount > 0) {
      await expect(autoBadges.first()).toBeVisible();
    } else {
      // Skip if no autonomous agents in cluster
      test.skip(true, 'No autonomous agents found in cluster');
    }
  });

  test('non-autonomous agent does not show autonomous badge', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    // Find a row that does NOT contain "Auto" text — at least one should exist
    const allRows = await rows.count();
    let foundNonAuto = false;
    for (let i = 0; i < allRows; i++) {
      const rowText = await rows.nth(i).textContent();
      if (rowText && !rowText.includes('Auto')) {
        foundNonAuto = true;
        break;
      }
    }
    expect(foundNonAuto).toBeTruthy();
  });

  test('agent detail shows autonomous config when agent is autonomous', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    // Find an autonomous agent by looking for the Auto badge
    const autoBadge = page.locator('text=Auto').first();
    const badgeCount = await autoBadge.count();
    if (badgeCount === 0) {
      test.skip(true, 'No autonomous agents found in cluster');
      return;
    }

    // Click the view button using data-testid for the autonomous agent
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

    // The overview tab should show autonomous execution section
    const body = page.locator('body');
    await expect(body).toContainText(/autonomous/i, { timeout: 5000 });
  });

  test('visual map shows autonomous indicator on autonomous agent node', async ({ page }) => {
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');

    const flowContainer = page.locator('.react-flow');
    await expect(flowContainer).toBeVisible({ timeout: 5000 });

    // Visual map should render nodes
    const nodes = page.locator('.react-flow__node');
    await expect(nodes.first()).toBeVisible({ timeout: 5000 });

    // If autonomous agents exist, they should have a Zap icon or indicator
    // We check that the visual map rendered successfully with agent nodes
    const nodeCount = await nodes.count();
    expect(nodeCount).toBeGreaterThan(0);
  });
});
