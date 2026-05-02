import { expect } from '@playwright/test';
import { navigateToTab, screenshot, setupVisualPage, test } from './fixtures/visual-test';
import { VISUAL_NAMESPACE } from './fixtures/mock-k8s';

test.describe('KAOS UI visual baseline', () => {
  test('app shell, overview, search, and theme states', async ({ page }) => {
    await setupVisualPage(page);
    await expect(page.getByRole('heading', { name: 'Dashboard Overview' })).toBeVisible();
    await screenshot(page, '01-app-shell-overview-populated.png');

    await page.getByTestId('global-search-input').click();
    await page.getByPlaceholder('Search ModelAPIs, MCPServers, Agents, Pods...').fill('planner');
    await screenshot(page, '02-global-search-results.png');
    await page.keyboard.press('Escape');

    await page.getByTestId('nav-settings').click();
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
    await screenshot(page, '03-settings-connectivity-dark.png');

    await page.getByRole('button', { name: /Appearance/ }).click();
    await screenshot(page, '04-settings-appearance-dark.png');

    await setupVisualPage(page, { theme: 'light' });
    await expect(page.getByRole('heading', { name: 'Dashboard Overview' })).toBeVisible();
    await screenshot(page, '05-app-shell-overview-light.png');
  });

  test('empty dashboard and lists', async ({ page }) => {
    await setupVisualPage(page, { scenario: 'empty' });
    await expect(page.getByRole('heading', { name: 'Dashboard Overview' })).toBeVisible();
    await screenshot(page, '06-dashboard-empty.png');

    await page.getByTestId('nav-agents').click();
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible();
    await screenshot(page, '07-agents-empty.png');

    await page.getByTestId('nav-secrets').click();
    await expect(page.getByRole('heading', { name: 'Secrets' })).toBeVisible();
    await screenshot(page, '08-secrets-empty.png');
  });

  test('visual map graph and controls', async ({ page }) => {
    await setupVisualPage(page);
    await navigateToTab(page, 'nav-visual-map');
    await expect(page.locator('.react-flow')).toBeVisible();
    await screenshot(page, '09-visual-map-populated.png');

    await page.getByPlaceholder('Search nodes...').fill('planner');
    await screenshot(page, '10-visual-map-search-filter.png');

    await page.getByRole('button', { name: 'MCPServer' }).click();
    await screenshot(page, '11-visual-map-kind-filter.png');
  });

  test('resource lists and create/delete overlays', async ({ page }) => {
    await setupVisualPage(page);

    await page.getByTestId('nav-agents').click();
    await expect(page.getByRole('heading', { name: 'Agents' })).toBeVisible();
    await screenshot(page, '12-agents-list-populated.png');
    await page.getByTestId('create-agents-button').click();
    await screenshot(page, '13-agent-create-dialog.png');
    await page.keyboard.press('Escape');

    await page.getByTestId('nav-mcp-servers').click();
    await expect(page.getByRole('heading', { name: 'MCP Servers' })).toBeVisible();
    await screenshot(page, '14-mcpservers-list-populated.png');

    await page.getByTestId('nav-model-apis').click();
    await expect(page.getByRole('heading', { name: 'Model APIs' })).toBeVisible();
    await screenshot(page, '15-modelapis-list-populated.png');

    await page.getByTestId('nav-pods').click();
    await expect(page.getByRole('heading', { name: 'Pods' })).toBeVisible();
    await screenshot(page, '16-pods-list-populated.png');

    await page.getByTestId('nav-secrets').click();
    await expect(page.getByRole('heading', { name: 'Secrets' })).toBeVisible();
    await screenshot(page, '17-secrets-list-populated.png');
    await page.getByRole('button', { name: 'Create Secret' }).click();
    await screenshot(page, '18-secret-create-dialog.png');
  });

  test('agent detail tabs and destructive confirmation', async ({ page }) => {
    const basePath = `/agents/${VISUAL_NAMESPACE}/planner-agent`;
    await setupVisualPage(page, { path: basePath });
    await expect(page.getByRole('heading', { name: 'planner-agent' })).toBeVisible();
    await screenshot(page, '19-agent-detail-overview.png');

    await page.getByTestId('tab-chat').click();
    await screenshot(page, '20-agent-detail-chat.png');

    await page.getByTestId('tab-a2a').click();
    await screenshot(page, '21-agent-detail-a2a.png');

    await page.getByTestId('tab-memory').click();
    await screenshot(page, '22-agent-detail-memory.png');

    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByTestId('tab-pods').click();
    await screenshot(page, '23-agent-detail-pods.png');

    await page.getByTestId('tab-yaml').click();
    await screenshot(page, '24-agent-detail-yaml.png');

    await page.getByRole('button', { name: 'Delete' }).click();
    await screenshot(page, '25-agent-delete-confirmation.png');
  });

  test('MCPServer detail tabs and tool debug', async ({ page }) => {
    const basePath = `/mcpservers/${VISUAL_NAMESPACE}/toolbox-server`;
    await setupVisualPage(page, { path: basePath });
    await expect(page.getByRole('heading', { name: 'toolbox-server' })).toBeVisible();
    await screenshot(page, '26-mcpserver-detail-overview.png');

    await page.getByRole('tab', { name: /tools/i }).click();
    await expect(page.getByRole('button', { name: /echo/i })).toBeVisible();
    await screenshot(page, '27-mcpserver-tool-debug.png');

    await page.getByRole('tab', { name: /pods/i }).click();
    await screenshot(page, '28-mcpserver-detail-pods.png');

    await page.getByRole('tab', { name: /yaml/i }).click();
    await screenshot(page, '29-mcpserver-detail-yaml.png');
  });

  test('ModelAPI detail diagnostics and pod details', async ({ page }) => {
    const modelPath = `/modelapis/${VISUAL_NAMESPACE}/primary-model-api`;
    await setupVisualPage(page, { path: modelPath });
    await expect(page.getByRole('heading', { name: 'primary-model-api' })).toBeVisible();
    await screenshot(page, '30-modelapi-detail-overview.png');

    await page.getByRole('tab', { name: /diagnostics|debug/i }).click();
    await screenshot(page, '31-modelapi-diagnostics.png');

    await page.getByRole('tab', { name: /yaml/i }).click();
    await screenshot(page, '32-modelapi-detail-yaml.png');

    await setupVisualPage(page, { path: `/pods/${VISUAL_NAMESPACE}/agent-planner-agent-7d6f9b9d7c-abcde` });
    await expect(page.getByRole('heading', { name: 'agent-planner-agent-7d6f9b9d7c-abcde' })).toBeVisible();
    await screenshot(page, '33-pod-detail-overview.png');

    await page.getByRole('tab', { name: /logs/i }).click();
    await expect(page.getByText('health check passed')).toBeVisible();
    await screenshot(page, '34-pod-detail-logs.png');

    await page.getByRole('tab', { name: /yaml/i }).click();
    await screenshot(page, '35-pod-detail-yaml.png');
  });

  test('system, monitoring, and not found states', async ({ page }) => {
    await setupVisualPage(page);
    await page.getByTestId('nav-kaos-system').click();
    await expect(page.getByRole('heading', { name: /KAOS System/i })).toBeVisible();
    await screenshot(page, '36-kaos-system-overview.png');

    await setupVisualPage(page, { scenario: 'empty' });
    await page.getByTestId('nav-kaos-system').click();
    await expect(page.getByText('KAOS Not Found')).toBeVisible();
    await screenshot(page, '37-kaos-system-missing.png');

    await page.getByTestId('nav-kaos-monitoring').click();
    await expect(page.getByRole('heading', { name: 'KAOS Monitoring' })).toBeVisible();
    await expect(page.getByText('Monitoring Not Available')).toBeVisible();
    await screenshot(page, '38-kaos-monitoring-unavailable.png');

    await setupVisualPage(page, { path: `/agents/${VISUAL_NAMESPACE}/missing-agent` });
    await expect(page.getByText('Agent Not Found')).toBeVisible();
    await screenshot(page, '39-agent-not-found.png');

    await page.goto('/does-not-exist');
    await screenshot(page, '40-not-found-route.png');
  });
});
