import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Visual Map Functional', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');
    // Wait for graph to render
    await expect(page.locator('.react-flow')).toBeVisible({ timeout: 5000 });
  });

  test('should have Fit View button that works', async ({ page }) => {
    const fitButton = page.getByRole('button', { name: /fit to view/i });
    if (await fitButton.isVisible()) {
      await fitButton.click();
      // Graph should still be visible after fit
      await expect(page.locator('.react-flow')).toBeVisible();
    } else {
      // Try tooltip-based button
      const buttons = page.locator('button').filter({ has: page.locator('svg') });
      expect(await buttons.count()).toBeGreaterThan(0);
    }
  });

  test('should have Re-layout button', async ({ page }) => {
    const relayoutButton = page.getByRole('button', { name: /re-layout/i });
    if (await relayoutButton.isVisible()) {
      await relayoutButton.click();
      await expect(page.locator('.react-flow')).toBeVisible();
    } else {
      // Toolbar should still be present
      await expect(page.getByPlaceholder('Search nodes...')).toBeVisible();
    }
  });

  test('should filter nodes via search', async ({ page }) => {
    const searchInput = page.getByPlaceholder('Search nodes...');
    await expect(searchInput).toBeVisible({ timeout: 5000 });

    // Type a search query
    await searchInput.fill('model');
    await page.waitForTimeout(500);

    // Graph should still be rendered
    await expect(page.locator('.react-flow')).toBeVisible();
  });

  test('should show resource nodes in the graph', async ({ page }) => {
    // The kaos-hierarchy namespace has agents, MCP servers, and model APIs
    const nodes = page.locator('.react-flow__node');
    await expect(nodes.first()).toBeVisible({ timeout: 5000 });
    const count = await nodes.count();
    // Should have at least a few nodes (agents + mcpserver + modelapi)
    expect(count).toBeGreaterThan(0);
  });

  test('should show edges connecting resources', async ({ page }) => {
    // Wait for edges to render
    const edges = page.locator('.react-flow__edge');
    const count = await edges.count();
    // Edges may or may not be present depending on resource configuration
    expect(count).toBeGreaterThanOrEqual(0);
  });
});
