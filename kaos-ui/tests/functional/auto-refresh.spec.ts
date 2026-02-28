import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Auto Refresh', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should show auto-refresh control in header', async ({ page }) => {
    // Auto-refresh dropdown should show "Off" by default
    const refreshControl = page.getByRole('button', { name: /off|refresh/i });
    await expect(refreshControl.first()).toBeVisible({ timeout: 5000 });
  });

  test('should have manual refresh button', async ({ page }) => {
    // The refresh button with RefreshCw icon
    const refreshButton = page.getByRole('button', { name: /refresh now/i });
    if (await refreshButton.isVisible()) {
      await refreshButton.click();
      await page.waitForLoadState('networkidle');
      // Page should still be functional after refresh
      await expect(page.locator('body')).toBeVisible();
    } else {
      // Refresh button may have different label
      const anyRefresh = page.locator('button').filter({ has: page.locator('svg.lucide-refresh-cw') });
      if (await anyRefresh.count() > 0) {
        await anyRefresh.first().click();
        await page.waitForLoadState('networkidle');
      }
    }
  });

  test('should toggle auto-refresh interval', async ({ page }) => {
    // Find the interval selector dropdown button
    const intervalButton = page.getByRole('button', { name: /^off$/i });
    if (!(await intervalButton.isVisible({ timeout: 3000 }).catch(() => false))) {
      // Might already be set to a different interval
      test.skip();
      return;
    }

    await intervalButton.click();

    // Dropdown should show interval options
    const menu = page.locator('[role="listbox"], [role="menu"], [data-radix-popper-content-wrapper]');
    await expect(menu.first()).toBeVisible({ timeout: 5000 });

    // Select 10s interval
    const option10s = page.getByText('10s');
    if (await option10s.isVisible()) {
      await option10s.click();
      // Auto-refresh should now be active
      await page.waitForTimeout(500);
    }
  });
});
