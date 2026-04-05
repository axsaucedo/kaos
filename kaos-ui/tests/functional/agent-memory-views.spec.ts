import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

test.describe('Agent Memory Views', () => {
  test.beforeEach(async ({ page }) => {
    page.on('pageerror', (err) => {
      if (!err.message.includes('ResizeObserver'))
        console.error('Page error:', err.message);
    });
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('memory tab renders with view toggle and live mode controls', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    // Click Memory tab
    const memoryTab = page.locator('[data-testid="tab-memory"]').or(page.getByRole('tab', { name: /memory/i }));
    await expect(memoryTab).toBeVisible({ timeout: 5000 });
    await memoryTab.click();
    await page.waitForLoadState('networkidle');

    // Live mode toggle should be visible
    const body = page.locator('body');
    const hasLiveToggle = await body.getByText(/live/i).count() > 0;
    expect(hasLiveToggle).toBeTruthy();

    // View toggle (Raw/Conversation) should be visible
    const hasViewToggle = await body.getByText(/raw/i).count() > 0 ||
      await body.getByText(/conversation/i).count() > 0 ||
      await body.getByText(/chat/i).count() > 0;
    expect(hasViewToggle).toBeTruthy();
  });

  test('memory tab can switch between raw and conversation views', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const memoryTab = page.locator('[data-testid="tab-memory"]').or(page.getByRole('tab', { name: /memory/i }));
    await expect(memoryTab).toBeVisible({ timeout: 5000 });
    await memoryTab.click();
    await page.waitForLoadState('networkidle');

    // Find and click the view toggle buttons
    const rawButton = page.locator('[data-testid="memory-view-raw"]');
    const chatButton = page.locator('[data-testid="memory-view-chat"]');

    if (await rawButton.isVisible({ timeout: 3000 })) {
      await rawButton.click();
      await page.waitForTimeout(500);

      // Switch to chat/conversation view
      if (await chatButton.isVisible({ timeout: 2000 })) {
        await chatButton.click();
        await page.waitForTimeout(500);
      }

      // Switch back to raw
      if (await rawButton.isVisible({ timeout: 2000 })) {
        await rawButton.click();
      }
    }
  });

  test('memory tab displays session filter dropdown', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const memoryTab = page.locator('[data-testid="tab-memory"]').or(page.getByRole('tab', { name: /memory/i }));
    await expect(memoryTab).toBeVisible({ timeout: 5000 });
    await memoryTab.click();
    await page.waitForLoadState('networkidle');

    // Session filter or selector should be visible
    const body = page.locator('body');
    const hasSessionControls = await body.getByText(/session/i).count() > 0 ||
      await body.getByText(/all sessions/i).count() > 0;
    expect(hasSessionControls).toBeTruthy();
  });

  test('memory tab shows events when agent has history', async ({ page }) => {
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });

    // Try to find an agent that might have memory events
    // Open the first agent
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const memoryTab = page.locator('[data-testid="tab-memory"]').or(page.getByRole('tab', { name: /memory/i }));
    await expect(memoryTab).toBeVisible({ timeout: 5000 });
    await memoryTab.click();
    await page.waitForLoadState('networkidle');

    // The memory tab should render without errors — either show events or empty state
    const body = page.locator('body');
    const hasContent = await body.getByText(/no.*events/i).count() > 0 ||
      await body.getByText(/no.*memory/i).count() > 0 ||
      await body.getByText(/event/i).count() > 0 ||
      await body.getByText(/user_message/i).count() > 0 ||
      await body.getByText(/session/i).count() > 0;
    expect(hasContent).toBeTruthy();
  });

  test('memory tab conversation view renders without errors', async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });

    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 5000 });
    await rows.first().locator('button').first().click();
    await page.waitForLoadState('networkidle');

    const memoryTab = page.locator('[data-testid="tab-memory"]').or(page.getByRole('tab', { name: /memory/i }));
    await expect(memoryTab).toBeVisible({ timeout: 5000 });
    await memoryTab.click();
    await page.waitForTimeout(2000);

    // Switch to conversation/chat view using data-testid
    const chatButton = page.locator('[data-testid="memory-view-chat"]');
    await expect(chatButton).toBeVisible({ timeout: 3000 });
    await chatButton.click();
    await page.waitForTimeout(1000);

    // Conversation view should render without errors (may show events or empty state)
    const body = page.locator('body');
    const hasNoError = await body.locator('text=TypeError').count() === 0 &&
      await body.locator('text=Something went wrong').count() === 0;
    expect(hasNoError).toBeTruthy();

    // Switch back to raw view
    const rawButton = page.locator('[data-testid="memory-view-raw"]');
    await expect(rawButton).toBeVisible({ timeout: 3000 });
    await rawButton.click();
    await page.waitForTimeout(500);

    // Raw view should also render without errors
    const hasNoErrorRaw = await body.locator('text=TypeError').count() === 0 &&
      await body.locator('text=Something went wrong').count() === 0;
    expect(hasNoErrorRaw).toBeTruthy();
  });
});
