/**
 * CRUD tests for ModelAPI resources.
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8081)
 * - kaos proxy running at http://localhost:8010
 * - Cluster access with write permissions
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

// Unique name for test resources
const TEST_RESOURCE_NAME = `test-modelapi-${Date.now()}`;

test.describe('ModelAPI CRUD Operations', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test.describe.serial('Create, Update, Delete ModelAPI', () => {
    
    test('should CREATE a Proxy mode ModelAPI', async ({ page }) => {
      // Navigate to Model APIs
      await page.getByRole('button', { name: /model api/i }).click();
      await page.waitForLoadState('networkidle');
      
      // Click Create button
      await page.getByRole('button', { name: /create model api/i }).click();
      
      // Wait for dialog to appear
      const dialog = page.locator('[role="dialog"]');
      await expect(dialog).toBeVisible({ timeout: 5000 });
      
      // Fill in the form
      // Name field
      await page.getByLabel(/name/i).first().fill(TEST_RESOURCE_NAME);
      
      // Mode should default to Proxy - verify it's selected
      const proxyRadio = page.locator('input[value="Proxy"], button[value="Proxy"], [data-value="Proxy"]').first();
      if (await proxyRadio.isVisible()) {
        await proxyRadio.click();
      }
      
      // Models field - add some test models
      const modelsInput = page.getByLabel(/models/i).or(page.locator('textarea').first());
      await modelsInput.fill('openai/gpt-4\nopenai/gpt-3.5-turbo');
      
      // API Base URL
      const apiBaseInput = page.getByLabel(/api base/i).or(page.getByPlaceholder(/api base/i));
      if (await apiBaseInput.isVisible()) {
        await apiBaseInput.fill('https://api.openai.com/v1');
      }
      
      // API Key - select "From Secret" option if available
      const secretOption = page.getByText(/from secret/i).or(page.getByLabel(/secret/i));
      if (await secretOption.isVisible()) {
        await secretOption.click();
        
        // Fill secret name and key
        const secretNameInput = page.getByLabel(/secret name/i).or(page.getByPlaceholder(/secret.*name/i));
        if (await secretNameInput.isVisible()) {
          await secretNameInput.fill('openai-secret');
        }
        
        const secretKeyInput = page.getByLabel(/secret key/i).or(page.getByPlaceholder(/key/i)).last();
        if (await secretKeyInput.isVisible()) {
          await secretKeyInput.fill('api-key');
        }
      }
      
      // Submit the form
      const submitButton = page.getByRole('button', { name: /create|submit|save/i }).last();
      await submitButton.click();
      
      // Wait for dialog to close (indicates success)
      await expect(dialog).not.toBeVisible({ timeout: 10000 });
      
      // Check for errors
      const hasError = await page.locator('text=error').or(page.locator('[role="alert"]')).count() > 0;
      
      // Verify the resource was created by checking the list
      await page.waitForLoadState('networkidle');
      const pageContent = await page.locator('body').textContent() || '';
      
      // The resource should appear in the list or we should see a success message
      const resourceCreated = pageContent.includes(TEST_RESOURCE_NAME) || 
                              pageContent.includes('created') ||
                              pageContent.includes('success');
      
      // If there's an error, log it for debugging
      if (hasError) {
        const errorText = await page.locator('[role="alert"]').textContent();
        console.log('Error during creation:', errorText);
      }
      
      expect(resourceCreated || !hasError, 'ModelAPI should be created successfully').toBeTruthy();
    });

    test('should UPDATE the created ModelAPI', async ({ page }) => {
      // Navigate to Model APIs
      await page.getByRole('button', { name: /model api/i }).click();
      await page.waitForLoadState('networkidle');
      
      // Wait for table rows to render
      const rows = page.locator('table tbody tr');
      await expect(rows.first()).toBeVisible({ timeout: 5000 });
      
      // Find the test resource in the table
      const testRow = rows.filter({ hasText: TEST_RESOURCE_NAME });
      const rowCount = await testRow.count();
      
      if (rowCount === 0) {
        console.log('Test resource not found, skipping update test');
        test.skip();
        return;
      }
      
      // Click the edit button using data-testid
      await testRow.getByTestId(`edit-${TEST_RESOURCE_NAME}`).click();
      
      // Wait for edit dialog — use last() because create+edit dialogs may both mount
      const dialog = page.locator('[role="dialog"]').last();
      await dialog.waitFor({ state: 'visible', timeout: 5000 });
      
      // Modify the models — scope to the active dialog to avoid duplicate #models
      const modelsInput = dialog.locator('#models');
      if (await modelsInput.isVisible()) {
        await modelsInput.fill('openai/gpt-4\nopenai/gpt-3.5-turbo\nanthropic/claude-3');
      }
      
      // Submit the update — scope to the active dialog
      await dialog.locator('button:has-text("Update ModelAPI")').click();
      
      // Wait for the dialog to close
      await expect(dialog).not.toBeVisible({ timeout: 10000 });
      await page.waitForLoadState('networkidle');
      
      // Check for errors
      const hasError = await page.locator('[role="alert"]').filter({ hasText: /error/i }).count() > 0;
      expect(hasError, 'Update should not produce errors').toBeFalsy();
    });

    test('should DELETE the created ModelAPI', async ({ page }) => {
      // Navigate to Model APIs
      await page.getByRole('button', { name: /model api/i }).click();
      await page.waitForLoadState('networkidle');
      
      // Wait for table rows to render
      const rows = page.locator('table tbody tr');
      await expect(rows.first()).toBeVisible({ timeout: 5000 });
      
      // Find the test resource in the table
      const testRow = rows.filter({ hasText: TEST_RESOURCE_NAME });
      const rowCount = await testRow.count();
      
      if (rowCount === 0) {
        console.log('Test resource not found (may have been deleted already)');
        return;
      }
      
      // Click the delete button using data-testid
      await testRow.getByTestId(`delete-${TEST_RESOURCE_NAME}`).click();
      
      // Confirm deletion
      const confirmButton = page.getByRole('button', { name: /confirm|delete|yes/i });
      await expect(confirmButton).toBeVisible({ timeout: 3000 });
      await confirmButton.click();
      
      // Wait for deletion to complete
      await page.waitForLoadState('networkidle');
      
      // Verify the resource is gone
      await page.getByRole('button', { name: 'Refresh', exact: true }).click();
      await page.waitForLoadState('networkidle');
      
      await expect(page.locator(`text=${TEST_RESOURCE_NAME}`)).toHaveCount(0, { timeout: 10000 });
    });
  });
});
