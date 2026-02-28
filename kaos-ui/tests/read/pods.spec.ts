import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Pods Read', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should navigate to pods page via sidebar', async ({ page }) => {
    await page.getByRole('button', { name: /pods/i }).click();
    await page.waitForLoadState('networkidle');

    await expect(page.getByRole('heading', { name: /pods/i })).toBeVisible({ timeout: 5000 });
  });

  test('should show pods in the list', async ({ page }) => {
    await page.getByRole('button', { name: /pods/i }).click();
    await page.waitForLoadState('networkidle');

    // Pods page uses card layout with pod names
    await expect(page.getByText('Running').first()).toBeVisible({ timeout: 5000 });
  });

  test('should show pod status badges', async ({ page }) => {
    await page.getByRole('button', { name: /pods/i }).click();
    await page.waitForLoadState('networkidle');

    // Pods should show Running status
    await expect(page.getByText('Running').first()).toBeVisible({ timeout: 5000 });
  });

  test('should navigate to pod detail on click', async ({ page }) => {
    await page.getByRole('button', { name: /pods/i }).click();
    await page.waitForLoadState('networkidle');

    // Click on the first pod card (they have cursor=pointer)
    const podCards = page.locator('[class*="cursor-pointer"]').filter({ hasText: /running|pending/i });
    await expect(podCards.first()).toBeVisible({ timeout: 5000 });
    await podCards.first().click();
    await page.waitForLoadState('networkidle');

    // Should navigate to pod detail page
    await expect(page).toHaveURL(/\/pods\/[^/]+\/[^/]+/, { timeout: 5000 });
  });
});
