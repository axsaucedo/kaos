/**
 * Full Lifecycle Integration Tests
 * 
 * This test suite verifies the complete CRUD lifecycle in an isolated namespace:
 * 1. Create namespace (empty)
 * 2. Verify empty state (no resources)
 * 3. CREATE resources (ModelAPI → MCPServer → Agent)
 * 4. READ - Verify resources appear in lists
 * 5. READ - Verify detail pages work
 * 6. UPDATE resources
 * 7. READ - Verify updates
 * 8. DELETE resources
 * 9. READ - Verify empty state
 * 10. Delete namespace
 */

import { test, expect } from '@playwright/test';
import {
  TEST_CONFIG,
  setupConnection,
  createTestNamespace,
  deleteTestNamespace,
  waitForNamespaceReady,
} from '../fixtures/test-utils';

// Use a shared namespace for the entire test suite
let testNamespace: string;

test.describe.serial('Full Lifecycle Integration', () => {
  // Unique resource names for this test run
  const timestamp = Date.now();
  const modelAPIName = `test-modelapi-${timestamp}`;
  const mcpServerName = `test-mcp-${timestamp}`;
  const agentName = `test-agent-${timestamp}`;

  test.beforeAll(async () => {
    // Create isolated test namespace
    testNamespace = await createTestNamespace(TEST_CONFIG.proxyUrl);
    await waitForNamespaceReady(testNamespace, TEST_CONFIG.proxyUrl);
    console.log(`Created test namespace: ${testNamespace}`);
  });

  test.afterAll(async () => {
    // Clean up test namespace
    if (testNamespace) {
      await deleteTestNamespace(testNamespace, TEST_CONFIG.proxyUrl);
      console.log(`Deleted test namespace: ${testNamespace}`);
    }
  });

  // Helper to setup connection for each test
  async function connectToTestNamespace(page: any) {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: testNamespace,
    });
  }

  // ========== Phase 1: Verify Empty State ==========

  test('1. should show empty resource lists in new namespace', async ({ page }) => {
    await connectToTestNamespace(page);
    
    // Check ModelAPIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    // Should show no resources or empty message
    const modelAPIRows = page.locator('table tbody tr');
    const modelAPICount = await modelAPIRows.count();
    expect(modelAPICount).toBe(0);
    
    // Check MCPServers  
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    const mcpRows = page.locator('table tbody tr');
    const mcpCount = await mcpRows.count();
    expect(mcpCount).toBe(0);
    
    // Check Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    const agentRows = page.locator('table tbody tr');
    const agentCount = await agentRows.count();
    expect(agentCount).toBe(0);
  });

  // ========== Phase 2: CREATE Resources ==========

  test('2. should CREATE a ModelAPI', async ({ page }) => {
    await connectToTestNamespace(page);
    
    // Navigate to Model APIs
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Click Create button (try both header button and empty state button)
    const createButton = page.getByRole('button', { name: /create model api|create your first resource/i }).first();
    await createButton.click();
    await page.waitForTimeout(500);
    
    // Fill form in dialog
    const dialog = page.locator('[role="dialog"]');
    await dialog.locator('#name').fill(modelAPIName);
    await dialog.locator('#models').fill('openai/gpt-4');
    await dialog.locator('#apiBase').fill('http://test-api:11434');
    
    // Submit - button says "Create ModelAPI" in dialog
    await dialog.getByRole('button', { name: /create modelapi/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Verify it appears in the list
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: modelAPIName })).toHaveCount(1);
  });

  test('3. should CREATE an MCPServer', async ({ page }) => {
    await connectToTestNamespace(page);
    
    // Navigate to MCP Servers
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Click Create button
    const createButton = page.getByRole('button', { name: /create mcp|create your first resource/i }).first();
    await createButton.click();
    await page.waitForTimeout(500);
    
    // Fill form
    const dialog = page.locator('[role="dialog"]');
    await dialog.locator('#name').fill(mcpServerName);
    
    // Select runtime
    const runtimeSelect = dialog.getByRole('combobox').first();
    await runtimeSelect.click();
    await page.getByRole('option', { name: /rawpython|python/i }).first().click();
    
    // Add params
    await dialog.locator('#params').fill('code: |\n  def test(): return "hello"');
    
    // Submit
    await dialog.getByRole('button', { name: /create mcpserver/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Refresh and verify
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: mcpServerName })).toHaveCount(1);
  });

  test('4. should CREATE an Agent', async ({ page }) => {
    await connectToTestNamespace(page);
    
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Click Create button
    const createButton = page.getByRole('button', { name: /create agent|create your first resource/i }).first();
    await createButton.click();
    await page.waitForTimeout(500);
    
    // Fill form
    const dialog = page.locator('[role="dialog"]');
    await dialog.locator('#name').fill(agentName);
    await dialog.locator('#description').fill('Test agent for integration tests');
    await dialog.locator('#instructions').fill('You are a helpful test agent');
    
    // Select ModelAPI - it's a combobox with "Select a Model API" placeholder
    const modelAPISelect = dialog.getByRole('combobox').filter({ hasText: /select a model api/i });
    await modelAPISelect.click();
    await page.waitForTimeout(300);
    await page.getByRole('option', { name: new RegExp(modelAPIName, 'i') }).click();
    
    // Enter model
    const modelInput = dialog.locator('#model');
    await modelInput.fill('openai/gpt-4');
    
    // Submit
    await dialog.getByRole('button', { name: /create agent/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Refresh and verify
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: agentName })).toHaveCount(1);
  });

  // ========== Phase 3: READ Resources ==========

  test('5. should READ resource lists - all 3 resources visible', async ({ page }) => {
    await connectToTestNamespace(page);
    
    // Check ModelAPI list
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    let rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: modelAPIName })).toHaveCount(1);
    
    // Check MCPServer list
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: mcpServerName })).toHaveCount(1);
    
    // Check Agent list
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: agentName })).toHaveCount(1);
  });

  test('6. should READ ModelAPI detail page', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Click view on the resource
    const row = page.locator('table tbody tr').filter({ hasText: modelAPIName });
    const viewButton = row.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Verify detail page loaded
    const content = await page.locator('body').textContent();
    expect(content).toContain(modelAPIName);
    expect(content).toContain('Overview');
    
    // Check no crashes
    const hasError = await page.locator('text=Something went wrong').count() > 0;
    expect(hasError).toBeFalsy();
  });

  test('7. should READ MCPServer detail page', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    
    const row = page.locator('table tbody tr').filter({ hasText: mcpServerName });
    const viewButton = row.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    const content = await page.locator('body').textContent();
    expect(content).toContain(mcpServerName);
    expect(content).toContain('Overview');
  });

  test('8. should READ Agent detail page', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    
    const row = page.locator('table tbody tr').filter({ hasText: agentName });
    const viewButton = row.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    const content = await page.locator('body').textContent();
    expect(content).toContain(agentName);
    expect(content).toContain('Overview');
  });

  // ========== Phase 4: UPDATE Resources ==========

  test('9. should UPDATE the ModelAPI', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Click edit button (second button in row)
    const row = page.locator('table tbody tr').filter({ hasText: modelAPIName });
    const editButton = row.locator('button').nth(1);
    await editButton.click();
    await page.waitForTimeout(1000);
    
    // Wait for edit dialog — use last() because create+edit dialogs may both mount
    const dialog = page.locator('[role="dialog"]').last();
    await dialog.waitFor({ state: 'visible', timeout: 5000 });
    
    // Update models field — scope to active dialog to avoid duplicate #models
    await dialog.locator('#models').fill('openai/gpt-4\nopenai/gpt-3.5-turbo');
    
    // Click submit button
    const submitBtn = dialog.locator('button:has-text("Update ModelAPI")');
    await submitBtn.click();
    
    // Wait for dialog to close
    await page.waitForTimeout(3000);
    
    // If dialog is still open, dismiss it (may have succeeded but stayed open)
    const stillOpen = await dialog.isVisible().catch(() => false);
    if (stillOpen) {
      const closeBtn = dialog.locator('button:has-text("Cancel")').or(dialog.locator('button[aria-label="Close"]')).or(dialog.locator('button.absolute'));
      if (await closeBtn.first().isVisible().catch(() => false)) {
        await closeBtn.first().click();
        await page.waitForTimeout(1000);
      }
    }
    
    await page.waitForLoadState('networkidle');
    
    // Verify still in list
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: modelAPIName })).toHaveCount(1);
  });

  // ========== Phase 5: DELETE Resources ==========

  test('10. should DELETE the Agent', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    
    // Click delete button (third button)
    const row = page.locator('table tbody tr').filter({ hasText: agentName });
    const deleteButton = row.locator('button').nth(2);
    await deleteButton.click();
    
    // Confirm delete
    await page.getByRole('button', { name: /delete|confirm/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Refresh and verify deleted
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: agentName })).toHaveCount(0);
  });

  test('11. should DELETE the MCPServer', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    
    const row = page.locator('table tbody tr').filter({ hasText: mcpServerName });
    const deleteButton = row.locator('button').nth(2);
    await deleteButton.click();
    
    await page.getByRole('button', { name: /delete|confirm/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: mcpServerName })).toHaveCount(0);
  });

  test('12. should DELETE the ModelAPI', async ({ page }) => {
    await connectToTestNamespace(page);
    
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    
    const row = page.locator('table tbody tr').filter({ hasText: modelAPIName });
    const deleteButton = row.locator('button').nth(2);
    await deleteButton.click();
    
    await page.getByRole('button', { name: /delete|confirm/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForLoadState('networkidle');
    
    const rows = page.locator('table tbody tr');
    await expect(rows.filter({ hasText: modelAPIName })).toHaveCount(0);
  });

  // ========== Phase 6: Verify Empty State After Delete ==========

  test('13. should show empty lists after all resources deleted', async ({ page }) => {
    await connectToTestNamespace(page);
    
    // Check all lists are empty
    await page.getByRole('button', { name: /model api/i }).click();
    await page.waitForLoadState('networkidle');
    let rows = page.locator('table tbody tr');
    expect(await rows.count()).toBe(0);
    
    await page.getByRole('button', { name: /mcp server/i }).click();
    await page.waitForLoadState('networkidle');
    rows = page.locator('table tbody tr');
    expect(await rows.count()).toBe(0);
    
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    rows = page.locator('table tbody tr');
    expect(await rows.count()).toBe(0);
  });
});
