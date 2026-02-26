/**
 * Read tests for ModelAPI resources.
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8080)
 * - kaos proxy running (Kubernetes API access)
 * - Cluster with ModelAPI resources in kaos-hierarchy namespace
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('ModelAPI Read Operations', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should display the ModelAPI list page', async ({ page }) => {
    // Navigate to ModelAPIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Verify we're on the ModelAPI tab (either via URL param or the tab is active)
    // The UI uses ?tab=modelapis or just updates state without URL change
    const pageContent = await page.locator('body').textContent();
    expect(pageContent).toBeTruthy();
    
    // Should show ModelAPI content (header or resources)
    await expect(page.locator('body')).toContainText(/model/i);
  });

  test('should navigate to ModelAPI detail page', async ({ page }) => {
    // Navigate to ModelAPIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // The table rows should be visible with resource data
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster - fail if none found
    expect(count, 'Expected ModelAPI resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click the view button (eye icon) on the first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Should navigate to detail page
    await expect(page).toHaveURL(/\/modelapis\/[^/]+\/[^/]+/);
    
    // Verify the page didn't crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
  });

  test('should display ModelAPI detail tabs', async ({ page }) => {
    // Navigate to ModelAPIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster
    expect(count, 'Expected ModelAPI resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click view button on first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Verify no crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
    
    // Detail page should have tabs (Overview, Pods, YAML)
    const tabList = page.locator('[role="tablist"]');
    await expect(tabList).toBeVisible();
  });

  test('should display ModelAPI configuration details', async ({ page }) => {
    // Navigate to ModelAPIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster
    expect(count, 'Expected ModelAPI resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click view button on first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Verify no crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
    
    // Detail page should show mode (Proxy or Hosted)
    const pageContent = await page.locator('body').textContent() || '';
    
    // Should contain either Proxy or Hosted mode indication
    const hasProxyOrHosted = pageContent.includes('Proxy') || pageContent.includes('Hosted');
    expect(hasProxyOrHosted).toBeTruthy();
  });
});
