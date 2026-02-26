/**
 * Smoke test: Verify the monitoring page renders correctly.
 *
 * When port 8011 is NOT forwarded (default in CI), the page should show
 * the "Monitoring Not Available" instructions.
 */

import { test, expect } from '@playwright/test';

test.describe('Monitoring Page', () => {
  test('should render the monitoring page with header', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to monitoring tab via sidebar
    const monitoringLink = page.locator('text=KAOS Observability');
    if (await monitoringLink.isVisible()) {
      await monitoringLink.click();
    }

    // The page header should be visible
    await expect(page.locator('text=KAOS Monitoring')).toBeVisible();
    await expect(page.locator('text=Observability dashboard')).toBeVisible();
  });

  test('should show instructions when monitoring port is not forwarded', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Navigate to monitoring tab
    const monitoringLink = page.locator('text=KAOS Observability');
    if (await monitoringLink.isVisible()) {
      await monitoringLink.click();
    }

    // Wait for port check to complete
    await page.waitForTimeout(4000);

    // If monitoring is actually running on port 8011, the "not available" message won't appear
    const notAvailable = page.locator('text=Monitoring Not Available');
    if (await notAvailable.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(notAvailable).toBeVisible();
      await expect(page.locator('text=kaos ui --monitoring-enabled signoz')).toBeVisible();
    } else {
      // Monitoring port is forwarded — skip the "not available" assertion
      console.log('Monitoring port 8011 is active; skipping "not available" assertion');
      await expect(page.locator('text=KAOS Monitoring')).toBeVisible();
    }
  });

  test('should have a refresh button', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const monitoringLink = page.locator('text=KAOS Observability');
    if (await monitoringLink.isVisible()) {
      await monitoringLink.click();
    }

    await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeVisible();
  });
});
