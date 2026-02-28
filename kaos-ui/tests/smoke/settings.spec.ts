import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Settings Page Smoke', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should load settings page via sidebar', async ({ page }) => {
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 5000 });
  });

  test('should show connectivity section', async ({ page }) => {
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: /kubernetes connection/i })).toBeVisible({ timeout: 5000 });
  });

  test('should show appearance section', async ({ page }) => {
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('Appearance', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });

  test('should navigate to settings and show heading', async ({ page }) => {
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('body')).toContainText(/configure your operator dashboard/i);
  });
});
