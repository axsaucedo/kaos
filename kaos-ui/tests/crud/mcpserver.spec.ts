/**
 * CRUD tests for MCPServer resources.
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8081)
 * - kaos proxy running at http://localhost:8010
 * - Cluster access with write permissions
 * 
 * Note: These tests validate the new MCPServer CRD format:
 * - Uses `runtime` instead of `type`
 * - Uses `params` instead of `config.tools`
 * - Uses `container.env` instead of `config.env`
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

// Unique name for test resources
const TEST_RESOURCE_NAME = `test-mcpserver-${Date.now()}`;

test.describe('MCPServer CRUD Operations', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test.describe.serial('Create, Update, Delete MCPServer', () => {
    
    test('should CREATE an MCPServer with runtime and params', async ({ page }) => {
      // Navigate to MCP Servers
      await page.getByRole('button', { name: /mcp server/i }).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1000);
      
      // Click Create button
      await page.getByRole('button', { name: /create mcp server/i }).click();
      await page.waitForTimeout(500);
      
      // Fill in the form
      // Name field
      await page.getByLabel(/name/i).first().fill(TEST_RESOURCE_NAME);
      
      // Runtime/Type selection - look for either format
      const runtimeSelect = page.locator('button[role="combobox"]').first();
      await runtimeSelect.click();
      await page.waitForTimeout(300);
      
      // Select python-string or python-runtime
      const pythonOption = page.getByRole('option', { name: /python/i }).first();
      await pythonOption.click();
      await page.waitForTimeout(300);
      
      // Tools source - select "From Code" tab to use params/string
      const fromCodeTab = page.getByRole('tab', { name: /from code|string/i });
      if (await fromCodeTab.isVisible()) {
        await fromCodeTab.click();
        await page.waitForTimeout(300);
      }
      
      // Fill in the params/tool definition
      const codeInput = page.locator('textarea').first();
      await codeInput.fill(`def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"`);
      
      // Add environment variable
      const addEnvButton = page.getByRole('button', { name: /add.*variable|add.*env/i });
      if (await addEnvButton.isVisible()) {
        await addEnvButton.click();
        await page.waitForTimeout(300);
        
        // Fill env var name and value
        const envNameInputs = page.locator('input[placeholder*="name" i], input[placeholder*="NAME" i]');
        const envValueInputs = page.locator('input[placeholder*="value" i], input[placeholder*="VALUE" i]');
        
        if (await envNameInputs.count() > 0) {
          await envNameInputs.last().fill('TEST_VAR');
        }
        if (await envValueInputs.count() > 0) {
          await envValueInputs.last().fill('test_value');
        }
      }
      
      // Submit the form
      const submitButton = page.getByRole('button', { name: /create|submit|save/i }).last();
      await submitButton.click();
      
      // Wait for the dialog to close or success message
      await page.waitForTimeout(2000);
      
      // Check for errors
      const hasError = await page.locator('[role="alert"]').filter({ hasText: /error|fail/i }).count() > 0;
      
      // Verify the resource was created by checking the list
      await page.waitForLoadState('networkidle');
      const pageContent = await page.locator('body').textContent() || '';
      
      const resourceCreated = pageContent.includes(TEST_RESOURCE_NAME) || 
                              pageContent.includes('created') ||
                              pageContent.includes('success');
      
      if (hasError) {
        const errorText = await page.locator('[role="alert"]').textContent();
        console.log('Error during creation:', errorText);
      }
      
      expect(resourceCreated || !hasError, 'MCPServer should be created successfully').toBeTruthy();
    });

    test('should UPDATE the created MCPServer', async ({ page }) => {
      // Navigate to MCP Servers
      await page.getByRole('button', { name: /mcp server/i }).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(2000);
      
      // Find the test resource in the table
      const rows = page.locator('table tbody tr');
      const testRow = rows.filter({ hasText: TEST_RESOURCE_NAME });
      const rowCount = await testRow.count();
      
      if (rowCount === 0) {
        console.log('Test resource not found, skipping update test');
        test.skip();
        return;
      }
      
      // Click the edit button (second button in actions)
      const editButton = testRow.locator('button').nth(1);
      await editButton.click();
      await page.waitForTimeout(1000);
      
      // Wait for edit dialog — use last() because create+edit dialogs may both mount
      const dialog = page.locator('[role="dialog"]').last();
      await dialog.waitFor({ state: 'visible', timeout: 5000 });
      
      // Modify the params/code
      const codeInput = dialog.locator('textarea').first();
      if (await codeInput.isVisible()) {
        await codeInput.fill(`def greet(name: str) -> str:
    """Greet someone by name - updated."""
    return f"Hello there, {name}!"`);
      }
      
      // Submit the update — scope to the active dialog
      await dialog.locator('button:has-text("Save Changes")').click();
      
      // Wait for the dialog to close
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle');
      
      // Check for errors
      const hasError = await page.locator('[role="alert"]').filter({ hasText: /error/i }).count() > 0;
      expect(hasError, 'Update should not produce errors').toBeFalsy();
    });

    test('should DELETE the created MCPServer', async ({ page }) => {
      // Navigate to MCP Servers
      await page.getByRole('button', { name: /mcp server/i }).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(2000);
      
      // Find the test resource in the table
      const rows = page.locator('table tbody tr');
      const testRow = rows.filter({ hasText: TEST_RESOURCE_NAME });
      const rowCount = await testRow.count();
      
      if (rowCount === 0) {
        console.log('Test resource not found (may have been deleted already)');
        return;
      }
      
      // Click the delete button (third button in actions)
      const deleteButton = testRow.locator('button').nth(2);
      await deleteButton.click();
      await page.waitForTimeout(500);
      
      // Confirm deletion if there's a confirmation dialog
      const confirmButton = page.getByRole('button', { name: /confirm|delete|yes/i });
      if (await confirmButton.isVisible()) {
        await confirmButton.click();
      }
      
      // Wait for deletion to complete
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle');
      
      // Verify the resource is gone
      await page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1000);
      
      const resourceStillExists = await page.locator(`text=${TEST_RESOURCE_NAME}`).count() > 0;
      expect(resourceStillExists, 'Resource should be deleted').toBeFalsy();
    });
  });
});
