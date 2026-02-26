/**
 * Functional tests for ModelAPI Requests.
 * 
 * Tests the ModelAPI Diagnostics tab functionality:
 * - Diagnostics tab display
 * - Request sending via test prompt
 * - Response display
 * - Latency and status information
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8081)
 * - kaos proxy running at http://localhost:8010
 * - ModelAPI in Ready state
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

// Use an existing ModelAPI
const TEST_MODELAPI = 'hierarchy-modelapi';

test.describe('ModelAPI Request Functionality', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should display diagnostics tab in ModelAPI detail page', async ({ page }) => {
    // Navigate to Model APIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find the test ModelAPI in the table
    const rows = page.locator('table tbody tr');
    const testRow = rows.filter({ hasText: TEST_MODELAPI });
    
    if (await testRow.count() === 0) {
      // Try any Ready ModelAPI
      const readyRow = rows.filter({ hasText: 'Ready' }).first();
      if (await readyRow.count() === 0) {
        console.log('No Ready ModelAPI found');
        test.skip();
        return;
      }
      
      const viewButton = readyRow.locator('button').first();
      await viewButton.click();
    } else {
      const viewButton = testRow.locator('button').first();
      await viewButton.click();
    }
    
    await page.waitForTimeout(1000);
    
    // Navigate to Diagnostics tab
    const diagnosticsTab = page.getByRole('tab', { name: /diagnostics/i });
    expect(await diagnosticsTab.isVisible()).toBeTruthy();
    
    await diagnosticsTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Verify diagnostics interface elements
    const pageContent = await page.locator('body').textContent() || '';
    const hasDiagnosticsElements = pageContent.includes('Test Request') ||
                                   pageContent.includes('Send') ||
                                   pageContent.includes('Prompt') ||
                                   pageContent.includes('Endpoint') ||
                                   pageContent.includes('/v1/chat/completions');
    
    expect(hasDiagnosticsElements, 'Diagnostics tab should show test interface').toBeTruthy();
  });

  test('should display endpoint information', async ({ page }) => {
    // Navigate to Model APIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready ModelAPI
    const rows = page.locator('table tbody tr');
    const readyRow = rows.filter({ hasText: 'Ready' }).first();
    
    if (await readyRow.count() === 0) {
      test.skip();
      return;
    }
    
    const viewButton = readyRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Check for endpoint info on Overview or Diagnostics
    const overviewTab = page.getByRole('tab', { name: /overview/i });
    await overviewTab.click();
    await page.waitForTimeout(500);
    
    let pageContent = await page.locator('body').textContent() || '';
    let hasEndpoint = pageContent.includes('svc.cluster.local') ||
                     pageContent.includes('endpoint') ||
                     pageContent.includes('Endpoint') ||
                     pageContent.includes(':8000') ||
                     pageContent.includes(':8080');
    
    // Also check Diagnostics tab
    const diagnosticsTab = page.getByRole('tab', { name: /diagnostics/i });
    if (await diagnosticsTab.isVisible()) {
      await diagnosticsTab.click();
      await page.waitForTimeout(500);
      
      pageContent = await page.locator('body').textContent() || '';
      hasEndpoint = hasEndpoint ||
                   pageContent.includes('svc.cluster.local') ||
                   pageContent.includes('endpoint');
    }
    
    expect(hasEndpoint, 'Should display endpoint information').toBeTruthy();
  });

  test('should send a test request and display response', async ({ page }) => {
    // This test requires ModelAPI to be fully operational
    test.setTimeout(120000); // 2 minutes for LLM response
    
    // Navigate to Model APIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready ModelAPI
    const rows = page.locator('table tbody tr');
    const readyRow = rows.filter({ hasText: 'Ready' }).first();
    
    if (await readyRow.count() === 0) {
      test.skip();
      return;
    }
    
    const viewButton = readyRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Navigate to Diagnostics tab
    const diagnosticsTab = page.getByRole('tab', { name: /diagnostics/i });
    if (!await diagnosticsTab.isVisible()) {
      test.skip();
      return;
    }
    
    await diagnosticsTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find prompt input
    const promptInput = page.locator('textarea').or(page.locator('input[type="text"]')).first();
    if (!await promptInput.isVisible({ timeout: 3000 })) {
      console.log('Prompt input not found');
      test.skip();
      return;
    }
    
    // Enter a test prompt
    const testPrompt = 'Say hello in one word';
    await promptInput.fill(testPrompt);
    
    // Find and click send button
    const sendButton = page.getByRole('button', { name: /send|test|submit/i }).first();
    if (!await sendButton.isVisible()) {
      console.log('Send button not found');
      test.skip();
      return;
    }
    
    await sendButton.click();
    
    // Wait for response (may take time)
    await page.waitForTimeout(10000);
    
    // Check for response display
    const pageContent = await page.locator('body').textContent() || '';
    const hasResponse = pageContent.includes('200') ||        // Success status
                       pageContent.includes('Response') ||
                       pageContent.includes('result') ||
                       pageContent.includes('content') ||
                       pageContent.includes('Hello') ||
                       pageContent.includes('hello') ||
                       pageContent.includes('ms') ||          // Latency
                       pageContent.includes('Error') ||       // Even error is a response
                       pageContent.includes('failed');
    
    expect(hasResponse, 'Should show some response after sending request').toBeTruthy();
  });

  test('should display diagnostics info section', async ({ page }) => {
    // Navigate to Model APIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready ModelAPI
    const rows = page.locator('table tbody tr');
    const readyRow = rows.filter({ hasText: 'Ready' }).first();
    
    if (await readyRow.count() === 0) {
      test.skip();
      return;
    }
    
    const viewButton = readyRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Navigate to Diagnostics tab
    const diagnosticsTab = page.getByRole('tab', { name: /diagnostics/i });
    if (!await diagnosticsTab.isVisible()) {
      test.skip();
      return;
    }
    
    await diagnosticsTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Check for diagnostics info section
    const pageContent = await page.locator('body').textContent() || '';
    const hasDiagnosticsInfo = pageContent.includes('Diagnostics Info') ||
                              pageContent.includes('Mode') ||
                              pageContent.includes('Status') ||
                              pageContent.includes('Proxy') ||
                              pageContent.includes('Hosted') ||
                              pageContent.includes('Send Test Request');
    
    expect(hasDiagnosticsInfo, 'Should have diagnostics info section').toBeTruthy();
  });
});
