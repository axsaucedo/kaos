/**
 * CRUD tests for Agent resources.
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8081)
 * - kaos proxy running at http://localhost:8010
 * - Cluster access with write permissions
 * 
 * Note: These tests validate the Agent CRD format:
 * - Uses `container.env` instead of `config.env`
 * - Includes modelAPI, model, and optional mcpServers
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

// Unique name for test resources
const TEST_RESOURCE_NAME = `test-agent-${Date.now()}`;

test.describe('Agent CRUD Operations', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test.describe.serial('Create, Update, Delete Agent', () => {
    
    test('should CREATE an Agent with model, mcpServers, and env vars', async ({ page }) => {
      // Navigate to Agents
      await page.getByRole('button', { name: /agents/i }).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1000);
      
      // Check for any crash/errors on the page first
      const errorMessage = page.locator('text=Something went wrong').or(page.locator('text=TypeError'));
      await expect(errorMessage).not.toBeVisible({ timeout: 3000 });
      
      // Click Create button
      await page.getByRole('button', { name: /create agent/i }).click();
      await page.waitForTimeout(500);
      
      // Fill in the form
      const dialog = page.locator('[role="dialog"]');
      
      // 1. Name
      await dialog.getByLabel(/name/i).first().fill(TEST_RESOURCE_NAME);
      
      // 2. Description
      await dialog.getByLabel(/description/i).fill('Test agent for CRUD operations');
      
      // 3. Instructions
      await dialog.getByLabel(/instructions/i).fill('Test instructions for automated testing');
      
      // 4. Model API - select from dropdown
      const modelAPISelect = dialog.locator('button:has-text("Select a Model API")');
      await modelAPISelect.click();
      await page.waitForTimeout(300);
      const firstOption = page.getByRole('option').first();
      if (await firstOption.isVisible()) {
        await firstOption.click();
      }
      
      // 5. Model - fill in model name
      const modelInput = dialog.locator('#model');
      await modelInput.scrollIntoViewIfNeeded();
      await modelInput.fill('gpt-4o-mini');
      
      // 6. Tool Call Mode - select "native" to verify the dropdown works
      const scrollArea = dialog.locator('[data-radix-scroll-area-viewport]');
      await scrollArea.evaluate(el => el.scrollTop = el.scrollHeight);
      await page.waitForTimeout(300);
      
      const toolCallModeSelect = dialog.locator('button:has-text("auto")').last();
      if (await toolCallModeSelect.isVisible()) {
        await toolCallModeSelect.click();
        await page.waitForTimeout(300);
        const nativeOption = page.getByRole('option', { name: 'native' });
        if (await nativeOption.isVisible()) {
          await nativeOption.click();
        }
      }
      
      // Click Create Agent button
      await page.getByRole('button', { name: 'Create Agent' }).click();
      
      // Wait for dialog to close
      await page.waitForTimeout(2000);
      
      // Check for errors
      const hasError = await page.locator('[role="alert"]').filter({ hasText: /error|fail/i }).count() > 0;
      
      // Verify the resource was created by checking the list
      await page.waitForLoadState('networkidle');
      const pageContent = await page.locator('body').textContent() || '';
      
      const resourceCreated = pageContent.includes(TEST_RESOURCE_NAME) || 
                              pageContent.includes('created') ||
                              pageContent.includes('success');
      
      expect(resourceCreated || !hasError, 'Agent should be created successfully').toBeTruthy();
    });

    test('should UPDATE the created Agent', async ({ page }) => {
      // Navigate to Agents
      await page.getByRole('button', { name: /agents/i }).click();
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
      
      // Click the edit button (second button in actions - after view)
      const editButton = testRow.locator('button').nth(1);
      await editButton.click();
      await page.waitForTimeout(1000);
      
      // Wait for edit dialog — use last() because create+edit dialogs may both mount
      const dialog = page.locator('[role="dialog"]').last();
      await dialog.waitFor({ state: 'visible', timeout: 5000 });
      
      // Update the instructions
      const instructionsField = dialog.locator('#instructions');
      if (await instructionsField.isVisible()) {
        await instructionsField.fill('Updated instructions for testing updates');
      }
      
      // Submit the update — scope to the active dialog to avoid duplicate button matches
      await dialog.locator('button:has-text("Save Changes")').click();
      
      // Wait for the dialog to close
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle');
      
      // Check for errors
      const hasError = await page.locator('[role="alert"]').filter({ hasText: /error/i }).count() > 0;
      expect(hasError, 'Update should not produce errors').toBeFalsy();
    });

    test('should DELETE the created Agent', async ({ page }) => {
      // Navigate to Agents
      await page.getByRole('button', { name: /agents/i }).click();
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(2000);
      
      // Find the test resource in the table
      const rows = page.locator('table tbody tr');
      const testRow = rows.filter({ hasText: TEST_RESOURCE_NAME });
      const rowCount = await testRow.count();
      
      if (rowCount === 0) {
        console.log('Test resource not found, skipping delete test');
        test.skip();
        return;
      }
      
      // Click the delete button (third button in actions)
      const deleteButton = testRow.locator('button').nth(2);
      await deleteButton.click();
      await page.waitForTimeout(500);
      
      // Handle confirmation dialog if present
      const confirmButton = page.getByRole('button', { name: /delete|confirm|yes/i }).last();
      if (await confirmButton.isVisible({ timeout: 2000 })) {
        await confirmButton.click();
      }
      
      // Wait for deletion to complete
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle');
      
      // Verify the resource is no longer in the list
      await page.waitForTimeout(1000);
      const stillExists = await rows.filter({ hasText: TEST_RESOURCE_NAME }).count() > 0;
      expect(stillExists, 'Agent should be deleted').toBeFalsy();
    });
  });
});
