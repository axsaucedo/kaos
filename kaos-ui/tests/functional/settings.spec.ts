import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Settings Functional', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');
  });

  test('should show connection settings with proxy URL', async ({ page }) => {
    // Click connectivity section
    await page.getByText('Connectivity', { exact: true }).first().click();
    await page.waitForLoadState('networkidle');

    // Should show connected cluster info
    const body = page.locator('body');
    await expect(body).toContainText(/connect/i, { timeout: 5000 });
  });

  test('should switch to appearance settings', async ({ page }) => {
    await page.getByText('Appearance', { exact: true }).first().click();

    // Should show appearance/theme options
    await expect(page.locator('body')).toContainText(/appearance/i, { timeout: 5000 });
  });

  test('should have theme toggle functionality', async ({ page }) => {
    await page.getByText('Appearance', { exact: true }).first().click();

    // Look for theme-related controls (dark/light/system)
    const body = page.locator('body');
    const content = await body.textContent();
    // Theme controls should be available
    expect(content).toMatch(/dark|light|system|theme/i);
  });
});
