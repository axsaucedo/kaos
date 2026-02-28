import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Error States', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should handle navigating to non-existent agent', async ({ page }) => {
    await page.goto(`/agents/${TEST_CONFIG.namespace}/nonexistent-agent-xyz-12345`);
    await page.waitForLoadState('networkidle');

    // Should show error or not found indication, not crash
    const body = page.locator('body');
    const content = await body.textContent();
    expect(content).toBeTruthy();
    // Should not show unhandled TypeError
    expect(content).not.toContain('TypeError');
  });

  test('should handle navigating to non-existent model API', async ({ page }) => {
    await page.goto(`/modelapis/${TEST_CONFIG.namespace}/nonexistent-modelapi-xyz-12345`);
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    const content = await body.textContent();
    expect(content).toBeTruthy();
    expect(content).not.toContain('TypeError');
  });

  test('should handle navigating to non-existent MCP server', async ({ page }) => {
    await page.goto(`/mcpservers/${TEST_CONFIG.namespace}/nonexistent-mcpserver-xyz-12345`);
    await page.waitForLoadState('networkidle');

    const body = page.locator('body');
    const content = await body.textContent();
    expect(content).toBeTruthy();
    expect(content).not.toContain('TypeError');
  });

  test('should handle navigating to non-existent namespace gracefully', async ({ page }) => {
    await page.goto(`/?kubernetesUrl=${encodeURIComponent(TEST_CONFIG.proxyUrl)}&namespace=nonexistent-ns-xyz-12345`);
    await page.waitForLoadState('networkidle');

    // App should still load without crashing
    const body = page.locator('body');
    await expect(body).toBeVisible();
    const content = await body.textContent();
    expect(content).not.toContain('TypeError');
  });
});
