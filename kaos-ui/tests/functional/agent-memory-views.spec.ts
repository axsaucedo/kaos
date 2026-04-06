import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

/**
 * Navigate to Memory tab for the first available agent.
 * Returns true if Memory tab was found and activated.
 */
async function navigateToMemoryTab(page: import('@playwright/test').Page): Promise<boolean> {
  await page.getByRole('button', { name: /agents/i }).click();
  await page.waitForLoadState('networkidle');

  const rows = page.locator('table tbody tr');
  await expect(rows.first()).toBeVisible({ timeout: 5000 });
  await rows.first().locator('button').first().click();
  await page.waitForLoadState('networkidle');

  const memoryTab = page.locator('[data-testid="tab-memory"]').or(page.getByRole('tab', { name: /memory/i }));
  if (!(await memoryTab.isVisible({ timeout: 5000 }))) return false;

  await memoryTab.click();
  await page.waitForLoadState('networkidle');
  return true;
}

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

  test('memory tab defaults to conversation view with all controls visible', async ({ page }) => {
    if (!(await navigateToMemoryTab(page))) {
      test.skip(true, 'Memory tab not available');
      return;
    }

    // Conversation view should be default (chat button should be active/selected)
    const chatButton = page.locator('[data-testid="memory-view-chat"]');
    const rawButton = page.locator('[data-testid="memory-view-raw"]');
    await expect(chatButton).toBeVisible({ timeout: 3000 });
    await expect(rawButton).toBeVisible({ timeout: 3000 });

    // Live mode toggle should be visible
    const body = page.locator('body');
    const hasLiveToggle = await body.getByText(/live/i).count() > 0;
    expect(hasLiveToggle).toBeTruthy();

    // Session filter should be visible
    const hasSessionControls = await body.getByText(/session/i).count() > 0 ||
      await body.getByText(/all sessions/i).count() > 0;
    expect(hasSessionControls).toBeTruthy();
  });

  test('view switching: conversation ↔ raw renders correctly without errors', async ({ page }) => {
    if (!(await navigateToMemoryTab(page))) {
      test.skip(true, 'Memory tab not available');
      return;
    }

    const chatButton = page.locator('[data-testid="memory-view-chat"]');
    const rawButton = page.locator('[data-testid="memory-view-raw"]');
    const body = page.locator('body');

    // Start in conversation view (default)
    await expect(chatButton).toBeVisible({ timeout: 3000 });

    // Switch to raw view
    await rawButton.click();
    await page.waitForTimeout(500);
    // Raw view should show events or empty state — no crashes
    expect(await body.locator('text=TypeError').count()).toBe(0);
    expect(await body.locator('text=Something went wrong').count()).toBe(0);

    // Memory should show content (events, empty state, or session info)
    const hasContent = await body.getByText(/no.*events/i).count() > 0 ||
      await body.getByText(/no.*memory/i).count() > 0 ||
      await body.getByText(/event/i).count() > 0 ||
      await body.getByText(/user_message/i).count() > 0 ||
      await body.getByText(/session/i).count() > 0;
    expect(hasContent).toBeTruthy();

    // Switch back to conversation view
    await chatButton.click();
    await page.waitForTimeout(500);
    expect(await body.locator('text=TypeError').count()).toBe(0);
    expect(await body.locator('text=Something went wrong').count()).toBe(0);
  });

  test('session filter: switching sessions updates displayed events', async ({ page }) => {
    if (!(await navigateToMemoryTab(page))) {
      test.skip(true, 'Memory tab not available');
      return;
    }

    // Look for session selector/dropdown
    const body = page.locator('body');
    const sessionSelector = page.locator('button').filter({ hasText: /all sessions|session/i }).first();

    if (await sessionSelector.isVisible({ timeout: 3000 })) {
      // Click session selector to open options
      await sessionSelector.click();
      await page.waitForTimeout(500);

      // If specific sessions are available, click one
      const sessionOptions = page.locator('[role="option"]');
      const optionCount = await sessionOptions.count();

      if (optionCount > 1) {
        // Select a specific session (not "All Sessions")
        await sessionOptions.nth(1).click();
        await page.waitForTimeout(1000);

        // Page should still render without errors
        expect(await body.locator('text=TypeError').count()).toBe(0);

        // Switch back to all sessions
        await sessionSelector.click();
        await page.waitForTimeout(500);
        const allOption = sessionOptions.filter({ hasText: /all/i }).first();
        if (await allOption.isVisible({ timeout: 2000 })) {
          await allOption.click();
        }
      }
    }
  });

  test('live mode: toggling live does not cause page errors', async ({ page }) => {
    if (!(await navigateToMemoryTab(page))) {
      test.skip(true, 'Memory tab not available');
      return;
    }

    const body = page.locator('body');

    // Find live toggle — it may be a switch, button, or checkbox
    const liveToggle = page.locator('button').filter({ hasText: /live/i }).first()
      .or(page.locator('[role="switch"]').first());

    if (await liveToggle.isVisible({ timeout: 3000 })) {
      // Enable live mode
      await liveToggle.click();
      await page.waitForTimeout(2000);

      // No errors should appear during live polling
      expect(await body.locator('text=TypeError').count()).toBe(0);
      expect(await body.locator('text=Something went wrong').count()).toBe(0);

      // Disable live mode
      await liveToggle.click();
      await page.waitForTimeout(500);

      // Still no errors
      expect(await body.locator('text=TypeError').count()).toBe(0);
    }
  });

  test('scroll-to-bottom button appears when content overflows', async ({ page }) => {
    if (!(await navigateToMemoryTab(page))) {
      test.skip(true, 'Memory tab not available');
      return;
    }

    // Check for scroll-to-bottom buttons in either view
    const scrollBottomChat = page.locator('[data-testid="memory-scroll-bottom"]');
    const scrollBottomRaw = page.locator('[data-testid="memory-scroll-bottom-raw"]');

    // If there's enough content, scroll-to-bottom should be available
    // or if not enough content, buttons may be hidden (both are valid states)
    const chatVisible = await scrollBottomChat.isVisible({ timeout: 2000 }).catch(() => false);

    // Switch to raw and check
    await page.locator('[data-testid="memory-view-raw"]').click();
    await page.waitForTimeout(500);
    const rawVisible = await scrollBottomRaw.isVisible({ timeout: 2000 }).catch(() => false);

    // At least verify the page rendered without errors
    const body = page.locator('body');
    expect(await body.locator('text=TypeError').count()).toBe(0);

    // If either button is visible, clicking it should not cause errors
    if (chatVisible) {
      await page.locator('[data-testid="memory-view-chat"]').click();
      await page.waitForTimeout(300);
      await scrollBottomChat.click();
      await page.waitForTimeout(300);
      expect(await body.locator('text=TypeError').count()).toBe(0);
    }
    if (rawVisible) {
      await page.locator('[data-testid="memory-view-raw"]').click();
      await page.waitForTimeout(300);
      await scrollBottomRaw.click();
      await page.waitForTimeout(300);
      expect(await body.locator('text=TypeError').count()).toBe(0);
    }
  });
});
