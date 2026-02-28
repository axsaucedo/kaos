import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Visual Map Smoke', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should load visual map page', async ({ page }) => {
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');

    // Visual map should render the ReactFlow container
    await expect(page.locator('.react-flow')).toBeVisible({ timeout: 5000 });
  });

  test('should show graph nodes for resources', async ({ page }) => {
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');

    // Should have nodes rendered in the graph
    const nodes = page.locator('.react-flow__node');
    await expect(nodes.first()).toBeVisible({ timeout: 5000 });
    const count = await nodes.count();
    expect(count).toBeGreaterThan(0);
  });

  test('should show toolbar with search input', async ({ page }) => {
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByPlaceholder('Search nodes...')).toBeVisible({ timeout: 5000 });
  });
});
