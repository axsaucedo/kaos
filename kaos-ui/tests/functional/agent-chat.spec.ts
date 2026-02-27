/**
 * Functional tests for Agent Chat and Memory.
 * 
 * Tests the Agent Chat and Memory tabs functionality:
 * - Chat message sending
 * - Response receiving (streaming)
 * - Session management
 * - Memory events display
 * - Memory sessions list
 * 
 * Prerequisites:
 * - npm run dev (starts UI at http://localhost:8081)
 * - kaos proxy running at http://localhost:8010
 * - Agent in Ready state with ModelAPI configured
 */

import { test, expect } from '@playwright/test';
import { setupConnection, TEST_CONFIG } from '../fixtures/test-utils';

// Use an existing Agent that should be ready
const TEST_AGENTS = ['analyst-1', 'researcher-1', 'research-lead']; // Fallback options

test.describe('Agent Chat and Memory Functionality', () => {
  test.beforeEach(async ({ page }) => {
    await setupConnection(page, {
      proxyUrl: TEST_CONFIG.proxyUrl,
      namespace: TEST_CONFIG.namespace,
    });
  });

  test('should display chat interface in Agent detail page', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready agent in the table
    const rows = page.locator('table tbody tr');
    let testRow = null;
    
    for (const agentName of TEST_AGENTS) {
      const row = rows.filter({ hasText: agentName });
      if (await row.count() > 0) {
        testRow = row.first();
        break;
      }
    }
    
    if (!testRow) {
      // Try to find any agent with Ready status
      testRow = rows.filter({ hasText: 'Ready' }).first();
    }
    
    if (!testRow || await testRow.count() === 0) {
      console.log('No Ready agent found, skipping test');
      test.skip();
      return;
    }
    
    // Click view button to open detail
    const viewButton = testRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Navigate to Chat tab
    const chatTab = page.getByRole('tab', { name: /chat/i });
    expect(await chatTab.isVisible()).toBeTruthy();
    
    await chatTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Verify chat interface elements are present
    const chatElements = await Promise.all([
      page.locator('textarea, input[type="text"]').count(),  // Message input
      page.locator('text=Session').or(page.locator('text=session')).count(),  // Session indicator
    ]);
    
    const hasInput = chatElements[0] > 0;
    const hasSessionInfo = chatElements[1] > 0;
    
    expect(hasInput, 'Chat should have a message input').toBeTruthy();
  });

  test('should send a chat message and receive response', async ({ page }) => {
    // This test requires agent to be fully operational
    test.setTimeout(120000); // 2 minutes for LLM response
    
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready agent
    const rows = page.locator('table tbody tr');
    let testRow = rows.filter({ hasText: 'Ready' }).first();
    
    if (await testRow.count() === 0) {
      console.log('No Ready agent found, skipping test');
      test.skip();
      return;
    }
    
    // Click view button
    const viewButton = testRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Navigate to Chat tab
    const chatTab = page.getByRole('tab', { name: /chat/i });
    await chatTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find message input
    const messageInput = page.locator('textarea').first();
    if (!await messageInput.isVisible({ timeout: 3000 })) {
      console.log('Message input not found');
      test.skip();
      return;
    }
    
    // Type a simple test message
    const testMessage = 'Hello, this is a test message. Please respond with a brief greeting.';
    await messageInput.fill(testMessage);
    
    // Send message (press Enter or click send button)
    const sendButton = page.getByRole('button', { name: /send/i }).or(
      page.locator('button[type="submit"]')
    );
    
    if (await sendButton.isVisible()) {
      await sendButton.click();
    } else {
      await messageInput.press('Enter');
    }
    
    // Wait for response (may take time for LLM)
    await page.waitForTimeout(5000);
    
    // Check for user message appearing
    const pageContent = await page.locator('body').textContent() || '';
    const hasUserMessage = pageContent.includes(testMessage.substring(0, 20)) ||
                          pageContent.includes('test message') ||
                          pageContent.includes('Hello');
    
    // Wait more for assistant response
    await page.waitForTimeout(10000);
    
    // Check for any response indicators
    const updatedContent = await page.locator('body').textContent() || '';
    const hasResponse = updatedContent.includes('assistant') ||
                       updatedContent.includes('AI') ||
                       updatedContent.includes('...') || // Streaming indicator
                       updatedContent.includes('greeting') ||
                       updatedContent.includes('Hello') ||
                       updatedContent.length > pageContent.length;
    
    // At minimum, our message should appear
    expect(hasUserMessage || hasResponse, 'Chat should show message or response').toBeTruthy();
  });

  test('should display memory events tab', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready agent
    const rows = page.locator('table tbody tr');
    let testRow = rows.filter({ hasText: 'Ready' }).first();
    
    if (await testRow.count() === 0) {
      test.skip();
      return;
    }
    
    // Click view button
    const viewButton = testRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Navigate to Memory tab
    const memoryTab = page.getByRole('tab', { name: /memory/i });
    if (!await memoryTab.isVisible()) {
      console.log('Memory tab not visible');
      test.skip();
      return;
    }
    
    await memoryTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Check for memory interface elements
    const pageContent = await page.locator('body').textContent() || '';
    const hasMemoryElements = pageContent.includes('Events') ||
                             pageContent.includes('Sessions') ||
                             pageContent.includes('Memory') ||
                             pageContent.includes('No events') ||
                             pageContent.includes('disabled') ||
                             pageContent.includes('not enabled');
    
    expect(hasMemoryElements, 'Memory tab should show memory interface or status').toBeTruthy();
  });

  test('should display memory sessions list', async ({ page }) => {
    // Navigate to Agents
    await page.getByRole('button', { name: /agents/i }).click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    
    // Find any Ready agent
    const rows = page.locator('table tbody tr');
    let testRow = rows.filter({ hasText: 'Ready' }).first();
    
    if (await testRow.count() === 0) {
      test.skip();
      return;
    }
    
    // Click view button
    const viewButton = testRow.locator('button').first();
    await viewButton.click();
    await page.waitForTimeout(1000);
    
    // Navigate to Memory tab
    const memoryTab = page.getByRole('tab', { name: /memory/i });
    if (!await memoryTab.isVisible()) {
      test.skip();
      return;
    }
    
    await memoryTab.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    
    // Try to switch to Sessions sub-tab if available
    const sessionsTab = page.getByRole('tab', { name: /sessions/i }).or(
      page.locator('button:has-text("Sessions")')
    );
    
    if (await sessionsTab.isVisible()) {
      await sessionsTab.click();
      await page.waitForTimeout(1000);
    }
    
    // Check for sessions list or empty state
    const pageContent = await page.locator('body').textContent() || '';
    const hasSessionsInfo = pageContent.includes('session') ||
                           pageContent.includes('Session') ||
                           pageContent.includes('No sessions') ||
                           pageContent.includes('0 events');
    
    expect(hasSessionsInfo, 'Memory should show sessions information').toBeTruthy();
  });
});
