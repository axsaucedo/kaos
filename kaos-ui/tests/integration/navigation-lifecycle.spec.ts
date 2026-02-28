import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Navigation Lifecycle', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should navigate through all main sections sequentially', async ({ page }) => {
    // 1. Summary (default landing)
    await page.getByRole('button', { name: /summary/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();

    // 2. Visual Map
    await page.getByRole('button', { name: /visual map/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('.react-flow')).toBeVisible({ timeout: 5000 });

    // 3. Model APIs
    await page.getByRole('button', { name: /model apis/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/model/i, { timeout: 5000 });

    // 4. MCP Servers
    await page.getByRole('button', { name: /mcp servers/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/mcp/i, { timeout: 5000 });

    // 5. Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/agent/i, { timeout: 5000 });

    // 6. Pods
    await page.getByRole('button', { name: /pods/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/pod/i, { timeout: 5000 });

    // 7. Secrets
    await page.getByRole('button', { name: /secrets/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: /secrets/i })).toBeVisible({ timeout: 5000 });

    // 8. KAOS System
    await page.locator('text=KAOS System').click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();

    // 9. KAOS Observability
    await page.locator('text=KAOS Observability').click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toBeVisible();

    // 10. Settings
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 5000 });
  });

  test('should maintain connection state across navigation', async ({ page }) => {
    // Navigate to agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/agent/i, { timeout: 5000 });

    // Navigate to settings
    await page.getByRole('button', { name: /settings/i }).click();
    await page.waitForLoadState('networkidle');

    // Go back to agents - data should still load
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(/agent/i, { timeout: 5000 });

    // No error should be shown
    const content = await page.locator('body').textContent();
    expect(content).not.toContain('Something went wrong');
    expect(content).not.toContain('TypeError');
  });
});
