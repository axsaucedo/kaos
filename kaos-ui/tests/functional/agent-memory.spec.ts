/**
 * Functional tests for Agent Memory event display.
 *
 * Tests memory event normalization (event_type→type, event_id→id),
 * structured content rendering for tool/delegation events,
 * and badge/icon display for all event types.
 *
 * Uses route interception to mock memory API responses so tests
 * are deterministic and don't require a live LLM.
 *
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8081)
 * - kaos proxy running at http://localhost:8010
 * - Agent in Ready state in kaos-hierarchy namespace
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

/** Mock memory events using backend field names (event_type, event_id) */
const MOCK_EVENTS = [
  {
    event_id: 'evt-001',
    event_type: 'user_message',
    content: 'What is 2 + 2?',
    timestamp: '2025-01-01T00:00:00Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-002',
    event_type: 'tool_call',
    content: { tool: 'calculator', arguments: { expression: '2 + 2' } },
    timestamp: '2025-01-01T00:00:01Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-003',
    event_type: 'tool_result',
    content: { tool: 'calculator', result: '4' },
    timestamp: '2025-01-01T00:00:02Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-004',
    event_type: 'tool_error',
    content: { tool: 'broken_tool', error: 'Connection timeout' },
    timestamp: '2025-01-01T00:00:03Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-005',
    event_type: 'delegation_request',
    content: { agent: 'researcher-1', task: 'Find recent papers on AI safety' },
    timestamp: '2025-01-01T00:00:04Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-006',
    event_type: 'delegation_response',
    content: { agent: 'researcher-1', response: 'Found 3 relevant papers' },
    timestamp: '2025-01-01T00:00:05Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-007',
    event_type: 'delegation_error',
    content: { agent: 'analyst-1', error: 'Agent unavailable' },
    timestamp: '2025-01-01T00:00:06Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-008',
    event_type: 'format_warning',
    content: 'Model returned malformed JSON in tool call arguments',
    timestamp: '2025-01-01T00:00:07Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-009',
    event_type: 'agent_response',
    content: 'The answer is 4.',
    timestamp: '2025-01-01T00:00:08Z',
    session_id: 'sess-abc123',
  },
  {
    event_id: 'evt-010',
    event_type: 'error',
    content: 'Unexpected error during processing',
    timestamp: '2025-01-01T00:00:09Z',
    session_id: 'sess-abc123',
  },
];

const MOCK_SESSIONS = ['sess-abc123'];

test.describe('Agent Memory Event Display', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  /**
   * Navigate to memory tab of a Ready agent, intercepting the memory API
   * to return mock events.
   */
  async function navigateToMemoryWithMock(page: import('@playwright/test').Page) {
    // Intercept memory events API
    await page.route('**/memory/events**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ events: MOCK_EVENTS }),
      });
    });

    // Intercept memory sessions API
    await page.route('**/memory/sessions**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: MOCK_SESSIONS }),
      });
    });

    // Navigate to Agents list
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);

    // Find a Ready agent
    const rows = page.locator('table tbody tr');
    const testRow = rows.filter({ hasText: 'Ready' }).first();
    if (await testRow.count() === 0) {
      return false;
    }

    // Open agent detail
    await testRow.locator('button').first().click();
    await page.waitForTimeout(1000);

    // Navigate to Memory tab
    const memoryTab = page.getByRole('tab', { name: /memory/i });
    if (!await memoryTab.isVisible()) {
      return false;
    }
    await memoryTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    return true;
  }

  test('should display normalized event badges for all event types', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Verify events tab shows correct count
    const eventsTab = page.locator('text=Events (');
    await expect(eventsTab).toBeVisible();

    // Check that badges render for key event types
    await expect(page.locator('text=User').first()).toBeVisible();
    await expect(page.locator('text=Agent').first()).toBeVisible();
    await expect(page.locator('text=Tool Call').first()).toBeVisible();
    await expect(page.locator('text=Tool Result').first()).toBeVisible();
    await expect(page.locator('text=Tool Error').first()).toBeVisible();
    await expect(page.locator('text=Delegation').first()).toBeVisible();
    await expect(page.locator('text=Delegation Result').first()).toBeVisible();
    await expect(page.locator('text=Delegation Error').first()).toBeVisible();
    await expect(page.locator('text=Warning').first()).toBeVisible();
    await expect(page.locator('text=Error').first()).toBeVisible();
  });

  test('should render structured tool call content with tool name and arguments', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Tool call should show tool name
    await expect(page.locator('text=calculator').first()).toBeVisible();

    // Tool call arguments should render
    await expect(page.locator('text=expression').first()).toBeVisible();
    await expect(page.locator('text=2 + 2').first()).toBeVisible();
  });

  test('should render structured tool result content', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Tool result should show the result value
    const resultIndicator = page.locator('text=→ 4');
    await expect(resultIndicator.first()).toBeVisible();
  });

  test('should render structured delegation request with agent name and task', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Delegation request should show agent name
    await expect(page.locator('text=researcher-1').first()).toBeVisible();

    // Delegation task should render
    await expect(page.locator('text=Find recent papers on AI safety').first()).toBeVisible();
  });

  test('should render structured delegation response with agent name and response', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Delegation response should show the response text
    await expect(page.locator('text=Found 3 relevant papers').first()).toBeVisible();
  });

  test('should render error events with error content', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Tool error should show error message
    await expect(page.locator('text=Connection timeout').first()).toBeVisible();

    // Delegation error should show error message
    await expect(page.locator('text=Agent unavailable').first()).toBeVisible();

    // General error should show
    await expect(page.locator('text=Unexpected error during processing').first()).toBeVisible();
  });

  test('should render format warning content', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    await expect(page.locator('text=malformed JSON').first()).toBeVisible();
  });

  test('should display session IDs in events', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Session ID should be visible (truncated)
    await expect(page.locator('text=sess-abc').first()).toBeVisible();
  });

  test('should show sessions tab with session list', async ({ page }) => {
    const navigated = await navigateToMemoryWithMock(page);
    if (!navigated) {
      test.skip();
      return;
    }

    // Switch to Sessions tab
    const sessionsTab = page.getByRole('tab', { name: /sessions/i });
    await sessionsTab.click();
    await page.waitForTimeout(500);

    // Session ID should be visible
    await expect(page.locator('text=sess-abc123').first()).toBeVisible();

    // Event count for the session
    await expect(page.locator('text=10 events').first()).toBeVisible();
  });
});
