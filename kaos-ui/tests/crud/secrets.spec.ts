import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe.serial('Secrets CRUD', () => {
  const TEST_SECRET_NAME = `test-secret-${Date.now()}`;

  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver')) console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
    await page.getByRole('button', { name: /secrets/i }).click();
    await page.waitForLoadState('networkidle');
  });

  test('should CREATE a new secret', async ({ page }) => {
    await page.getByRole('button', { name: /create secret/i }).click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5000 });

    // Fill in secret name using accessible name
    await dialog.getByRole('textbox', { name: /secret name/i }).fill(TEST_SECRET_NAME);

    // Fill key-value pair
    const keyInput = dialog.getByRole('textbox', { name: 'KEY' });
    if (await keyInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await keyInput.fill('API_KEY');
    }

    const valueInput = dialog.getByRole('textbox', { name: 'value' });
    if (await valueInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await valueInput.fill('test-value-12345');
    }

    // Click Create button in the dialog footer
    await dialog.getByRole('button', { name: 'Create Secret' }).click();

    // Wait for dialog to close and list to refresh
    await expect(dialog).not.toBeVisible({ timeout: 10000 });
    await page.waitForLoadState('networkidle');

    // Verify the secret appears in the list
    await expect(page.getByText(TEST_SECRET_NAME, { exact: true })).toBeVisible({ timeout: 10000 });
  });

  test('should DELETE the created secret', async ({ page }) => {
    const secretText = page.getByText(TEST_SECRET_NAME, { exact: true });
    if (!(await secretText.isVisible({ timeout: 5000 }).catch(() => false))) {
      test.skip();
      return;
    }

    // Each secret card is a .bg-card.rounded-xl container
    const secretCard = page.locator('.bg-card.rounded-xl').filter({ hasText: TEST_SECRET_NAME });
    await expect(secretCard).toBeVisible({ timeout: 5000 });

    // Click the delete button (destructive-colored trash icon) within this specific card
    await secretCard.locator('.text-destructive').click();

    // Confirm deletion in the AlertDialog
    const deleteButton = page.getByRole('button', { name: /^delete$/i }).last();
    await expect(deleteButton).toBeVisible({ timeout: 5000 });
    await deleteButton.click();

    await page.waitForLoadState('networkidle');
    await expect(page.getByText(TEST_SECRET_NAME, { exact: true })).not.toBeVisible({ timeout: 10000 });
  });
});
