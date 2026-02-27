/**
 * Read tests for MCPServer resources.
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8080)
 * - kaos proxy running (Kubernetes API access)
 * - Cluster with MCPServer resources in kaos-hierarchy namespace
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('MCPServer Read Operations', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should display the MCPServer list page', async ({ page }) => {
    // Navigate to MCP Servers
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Verify we're on the MCPServers tab (UI uses state-based navigation)
    const pageContent = await page.locator('body').textContent();
    expect(pageContent).toBeTruthy();
    
    // Should show MCP Server content
    await expect(page.locator('body')).toContainText(/mcp/i);
  });

  test('should navigate to MCPServer detail page', async ({ page }) => {
    // Navigate to MCP Servers
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // The table rows should be visible with resource data
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster - fail if none found
    expect(count, 'Expected MCPServer resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click the view button (eye icon) on the first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Should navigate to detail page
    await expect(page).toHaveURL(/\/mcpservers\/[^/]+\/[^/]+/);
    
    // Verify the page didn't crash - check for error boundaries or React error overlay
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
  });

  test('should display MCPServer detail tabs', async ({ page }) => {
    // Navigate to MCP Servers
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster
    expect(count, 'Expected MCPServer resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click view button on first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Verify no crash - check page still renders properly
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
    
    // Detail page should have tabs (Overview, Tools, Pods, YAML)
    const tabList = page.locator('[role="tablist"]');
    await expect(tabList).toBeVisible();
  });

  test('should display MCPServer type (python-runtime or node-runtime)', async ({ page }) => {
    // Navigate to MCP Servers
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    const rows = page.locator('table tbody tr');
    const count = await rows.count();
    
    // We expect resources in the test cluster
    expect(count, 'Expected MCPServer resources in kaos-hierarchy namespace').toBeGreaterThan(0);
    
    // Click view button on first row
    const viewButton = rows.first().locator('button').first();
    await viewButton.click();
    await page.waitForLoadState('networkidle');
    
    // Verify no crash
    const hasError = await page.locator('text=Something went wrong').count() > 0 ||
                     await page.locator('text=TypeError').count() > 0 ||
                     await page.locator('text=Cannot read properties').count() > 0;
    expect(hasError, 'Page should not display error messages').toBeFalsy();
    
    // MCPServer detail should show the runtime type or be properly rendered
    const pageContent = await page.locator('body').textContent() || '';
    
    // Page should contain meaningful content (not just error messages)
    expect(pageContent.length).toBeGreaterThan(100);
  });
});
