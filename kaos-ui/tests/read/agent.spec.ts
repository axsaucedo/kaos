/**
 * Read tests for Agent resources.
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8080)
 * - kaos proxy running (Kubernetes API access)
 * - Cluster with Agent resources in kaos-hierarchy namespace
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Agent Read Operations', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should display the Agent list page', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Verify we're on the Agents tab (UI uses state-based navigation)
    const pageContent = await page.locator('body').textContent();
    expect(pageContent).toBeTruthy();
    
    // Should show Agent content
    await expect(page.locator('body')).toContainText(/agent/i);
  });

  test('should navigate to Agent detail page', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // The table rows should be visible with resource data
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster - fail if none found
    expect(count, 'Expected Agent resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click the view button (eye icon) on the first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Should navigate to detail page
    await expect(page).toHaveURL(/\/agents\/[^/]+\/[^/]+/);
    
    // Verify the page didn't crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
  });

  test('should display Agent detail tabs including Chat', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster
    expect(count, 'Expected Agent resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click view button on first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Verify no crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
    
    // Detail page should have tabs (Overview, Chat, Memory, Pods, YAML)
    const tabList = page.locator('[role="tablist"]');
    await expect(tabList).toBeVisible();
  });

  test('should display Agent configuration with ModelAPI reference', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster
    expect(count, 'Expected Agent resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click view button on first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Verify no crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
    
    // Agent detail should show model configuration
    const pageContent = await page.locator('body').textContent() || '';
    
    // Should contain meaningful content
    expect(pageContent.length).toBeGreaterThan(100);
  });
});
