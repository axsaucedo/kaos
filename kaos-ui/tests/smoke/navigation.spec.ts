import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Navigation Smoke', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should navigate to settings via sidebar', async ({ page }) => {
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 5000 });
  });

  test('should navigate to agents via sidebar', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/agent/i);
  });

  test('should navigate to pods via sidebar', async ({ page }) => {
    await page.getByRole('button', { name: /pods/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/pod/i);
  });

  test('should navigate between sidebar sections', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/agent/i);

    // Navigate to Model APIs
    await page.getByRole('button', { name: /model apis/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/model/i);

    // Navigate to MCP Servers
    await page.getByRole('button', { name: /mcp servers/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/mcp/i);
  });

  test('should navigate to multiple sections without errors', async ({ page }) => {
    // Navigate to Agents then to Settings
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 5000 });

    // Navigate back to Summary
    await page.getByRole('button', { name: /summary/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();

    // No errors should be present
    const content = await page.locator('body').textContent();
    expect(content).not.toContain('TypeError');
  });
});
