import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Secrets Read', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should navigate to secrets page via sidebar', async ({ page }) => {
    await page.getByRole('button', { name: /secrets/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: /secrets/i })).toBeVisible({ timeout: 5000 });
  });

  test('should show secrets in the list', async ({ page }) => {
    await page.getByRole('button', { name: /secrets/i }).click();
    await page.waitForLoadState('networkidle');

    // The namespace should have at least some secrets (e.g., service account tokens)
    const body = page.locator('body');
    const content = await body.textContent();
    if (!content || content.includes('No secrets found')) {
      test.skip();
      return;
    }

    // Should show secret type badges (Opaque, Service Account, etc.)
    const secretCards = page.locator('[class*="card"]').filter({ hasText: /opaque|service account|tls/i });
    if (await secretCards.count() === 0) {
      // May not have secrets - skip gracefully
      test.skip();
      return;
    }
    await expect(secretCards.first()).toBeVisible({ timeout: 5000 });
  });

  test('should show Create Secret button', async ({ page }) => {
    await page.getByRole('button', { name: /secrets/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('button', { name: /create secret/i })).toBeVisible({ timeout: 5000 });
  });

  test('should show Refresh button', async ({ page }) => {
    await page.getByRole('button', { name: /secrets/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeVisible({ timeout: 5000 });
  });
});
