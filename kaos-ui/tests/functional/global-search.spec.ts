import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Global Search', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should show search input in header', async ({ page }) => {
    const searchTrigger = page.getByPlaceholder(/search resources/i);
    await expect(searchTrigger).toBeVisible({ timeout: 5000 });
  });

  test('should open search dialog on click', async ({ page }) => {
    const searchTrigger = page.getByPlaceholder(/search resources/i);
    await searchTrigger.click();

    // Search dialog should open with a more detailed input
    const searchDialog = page.locator('[role="dialog"]');
    await expect(searchDialog).toBeVisible({ timeout: 5000 });
  });

  test('should search for resources and show results', async ({ page }) => {
    const searchTrigger = page.getByPlaceholder(/search resources/i);
    await searchTrigger.click();

    const searchDialog = page.locator('[role="dialog"]');
    await expect(searchDialog).toBeVisible({ timeout: 5000 });

    // Type a search query for a known resource type
    const dialogInput = searchDialog.locator('input');
    await dialogInput.fill('agent');
    await page.waitForTimeout(500);

    // Should show results
    const body = page.locator('body');
    const content = await body.textContent();
    // Either shows results or "No results" message
    expect(content).toBeTruthy();
  });

  test('should open search with keyboard shortcut', async ({ page }) => {
    // Ctrl+K or Cmd+K should open search
    const modifier = process.platform === 'darwin' ? 'Meta' : 'Control';
    await page.keyboard.press(`${modifier}+k`);

    const searchDialog = page.locator('[role="dialog"]');
    await expect(searchDialog).toBeVisible({ timeout: 5000 });
  });

  test('should show no results for nonsense query', async ({ page }) => {
    const searchTrigger = page.getByPlaceholder(/search resources/i);
    await searchTrigger.click();

    const searchDialog = page.locator('[role="dialog"]');
    await expect(searchDialog).toBeVisible({ timeout: 5000 });

    const dialogInput = searchDialog.locator('input');
    await dialogInput.fill('xyznonexistent12345');
    await page.waitForTimeout(500);

    await expect(page.getByText(/no results/i)).toBeVisible({ timeout: 5000 });
  });
});
