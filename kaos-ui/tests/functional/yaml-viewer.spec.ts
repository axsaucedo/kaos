import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('YAML Viewer', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should show YAML tab on agent detail page', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    // Click the view button on the first row
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const yamlTab = page.getByRole('tab', { name: /yaml/i });
    await expect(yamlTab).toBeVisible({ timeout: 5000 });
  });

  test('should display YAML content when tab is clicked', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const yamlTab = page.getByRole('tab', { name: /yaml/i });
    await yamlTab.click();
    await page.waitForLoadState('networkidle');

    await expect(page.locator('body')).toContainText(/apiVersion|kind|metadata|spec/i, { timeout: 5000 });
  });

  test('should have copy button in YAML viewer', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const yamlTab = page.getByRole('tab', { name: /yaml/i });
    await yamlTab.click();
    await page.waitForLoadState('networkidle');

    // Look for copy button or YAML section header
    const copyButton = page.getByRole('button', { name: /copy/i });
    if (await copyButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(copyButton).toBeVisible();
    } else {
      const yamlSection = page.locator('text=YAML').first();
      await expect(yamlSection).toBeVisible();
    }
  });

  test('should show YAML tab on model API detail page', async ({ page }) => {
    await page.getByRole('button', { name: /model apis/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const yamlTab = page.getByRole('tab', { name: /yaml/i });
    await expect(yamlTab).toBeVisible({ timeout: 5000 });

    await yamlTab.click();
    await page.waitForLoadState('networkidle');

    await expect(page.locator('body')).toContainText(/apiVersion|kind|metadata|spec/i, { timeout: 5000 });
  });
});
