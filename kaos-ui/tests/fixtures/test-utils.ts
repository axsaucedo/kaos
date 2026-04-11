/**
 * Test utilities and fixtures for KAOS-UI Playwright tests.
 */

import { Page, expect } from '@playwright/test';

/** Default test configuration */
export const TEST_CONFIG = {
  proxyUrl: 'http://localhost:8010',
  namespace: 'kaos-hierarchy',
  baseUrl: 'http://localhost:8080',
};

/**
 * Generate a unique test namespace name.
 * Format: test-<short-hash>
 */
export function generateTestNamespace(): string {
  const hash = Math.random().toString(36).substring(2, 8);
  return `test-${hash}`;
}

/**
 * Create a test namespace via the Kubernetes API.
 * This creates an isolated namespace for test resources.
 */
export async function createTestNamespace(
  proxyUrl: string = TEST_CONFIG.proxyUrl,
  namespaceName?: string
): Promise<string> {
  const ns = namespaceName || generateTestNamespace();
  
  const response = await fetch(`${proxyUrl}/api/v1/namespaces`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      apiVersion: 'v1',
      kind: 'Namespace',
      metadata: {
        name: ns,
        labels: {
          'kaos-ui-test': 'true',
          'created-by': 'playwright',
        },
      },
    }),
  });

  if (!response.ok && response.status !== 409) {
    throw new Error(`Failed to create namespace ${ns}: ${response.status} ${response.statusText}`);
  }

  return ns;
}

/**
 * Delete a test namespace via the Kubernetes API.
 * This cleans up all resources in the namespace.
 */
export async function deleteTestNamespace(
  namespaceName: string,
  proxyUrl: string = TEST_CONFIG.proxyUrl
): Promise<void> {
  const response = await fetch(`${proxyUrl}/api/v1/namespaces/${namespaceName}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok && response.status !== 404) {
    console.warn(`Failed to delete namespace ${namespaceName}: ${response.status}`);
  }
}

/**
 * Wait for a namespace to be ready (active).
 */
export async function waitForNamespaceReady(
  namespaceName: string,
  proxyUrl: string = TEST_CONFIG.proxyUrl,
  timeoutMs: number = 30000
): Promise<void> {
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeoutMs) {
    try {
      const response = await fetch(`${proxyUrl}/api/v1/namespaces/${namespaceName}`);
      if (response.ok) {
        const ns = await response.json();
        if (ns.status?.phase === 'Active') {
          return;
        }
      }
    } catch {
      // Retry
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  
  throw new Error(`Namespace ${namespaceName} not ready after ${timeoutMs}ms`);
}

/**
 * Wait for a namespace to be fully deleted.
 */
export async function waitForNamespaceDeleted(
  namespaceName: string,
  proxyUrl: string = TEST_CONFIG.proxyUrl,
  timeoutMs: number = 60000
): Promise<void> {
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeoutMs) {
    try {
      const response = await fetch(`${proxyUrl}/api/v1/namespaces/${namespaceName}`);
      if (response.status === 404) {
        return; // Namespace deleted
      }
    } catch {
      return; // Connection error likely means deleted
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  
  console.warn(`Namespace ${namespaceName} not deleted after ${timeoutMs}ms`);
}

/**
 * Setup connection to the Kubernetes cluster via the KAOS proxy.
 * This configures the UI to connect to the local proxy.
 */
export async function setupConnection(
  page: Page,
  options: {
    proxyUrl?: string;
    namespace?: string;
  } = {}
): Promise<void> {
  const proxyUrl = options.proxyUrl || TEST_CONFIG.proxyUrl;
  const namespace = options.namespace || TEST_CONFIG.namespace;

  // Clear localStorage to prevent stale connection state
  await page.addInitScript(() => {
    localStorage.removeItem('k8s-config');
  });

  // Navigate with query params to auto-connect
  await page.goto(`/?kubernetesUrl=${encodeURIComponent(proxyUrl)}&namespace=${encodeURIComponent(namespace)}`);
  
  // Wait for the app to load
  await page.waitForLoadState('networkidle');

  // Wait for the "Disconnected" text in the header to disappear,
  // indicating the connection has been established
  const disconnectedBadge = page.locator('header').getByText('Disconnected')
    .or(page.locator('banner').getByText('Disconnected'));
  try {
    await expect(disconnectedBadge).not.toBeVisible({ timeout: 15000 });
  } catch {
    // If "Disconnected" is still visible, try clicking refresh to force reconnection
    const refreshButton = page.getByRole('button', { name: /refresh now/i });
    if (await refreshButton.isEnabled({ timeout: 1000 }).catch(() => false)) {
      await refreshButton.click();
      await page.waitForLoadState('networkidle');
    }
  }

  // Final wait for data to load
  await page.waitForLoadState('networkidle');
}

/**
 * Wait for a resource list to load.
 */
export async function waitForResourceList(
  page: Page,
): Promise<void> {
  // Wait for loading to complete
  await page.waitForLoadState('networkidle');
}

/**
 * Navigate to a specific resource detail page.
 */
export async function navigateToResource(
  page: Page,
  resourceType: 'agent' | 'mcpserver' | 'modelapi' | 'pod',
  name: string,
  namespace: string = TEST_CONFIG.namespace
): Promise<void> {
  const pathMap = {
    agent: 'agents',
    mcpserver: 'mcpservers',
    modelapi: 'modelapis',
    pod: 'pods',
  };
  
  await page.goto(`/${pathMap[resourceType]}/${namespace}/${name}`);
  await page.waitForLoadState('networkidle');
}

/**
 * Get all resource cards/items from a list page.
 */
export async function getResourceCards(
  page: Page,
): Promise<string[]> {
  // Wait for content to load
  await page.waitForLoadState('networkidle');

  // Resource cards typically have the resource name as text
  const cards = page.locator('[data-testid^="resource-"]');
  const count = await cards.count();
  
  const names: string[] = [];
  for (let i = 0; i < count; i++) {
    const text = await cards.nth(i).textContent();
    if (text) names.push(text);
  }
  
  return names;
}

/**
 * Check if a resource detail page shows the correct resource type and name.
 */
export async function verifyResourceDetail(
  page: Page,
  expectedName: string
): Promise<void> {
  // The page should contain the resource name
  await expect(page.getByText(expectedName, { exact: false })).toBeVisible();
}

/**
 * Click on a sidebar navigation item.
 */
export async function navigateViaSidebar(
  page: Page,
  section: 'Dashboard' | 'Agents' | 'MCP Servers' | 'Model APIs' | 'Pods' | 'Settings'
): Promise<void> {
  await page.getByRole('link', { name: section }).click();
  await page.waitForLoadState('networkidle');
}

/**
 * Wait for the connection status to show connected.
 */
export async function waitForConnected(page: Page): Promise<void> {
  // Look for indicators of successful connection
  // This could be a status badge, loaded resources, etc.
  await page.waitForLoadState('networkidle');
  
  // Wait for any loading spinners to disappear
  const spinner = page.locator('[data-testid="loading"]');
  if (await spinner.isVisible()) {
    await expect(spinner).not.toBeVisible({ timeout: 10000 });
  }
}

/**
 * Get the count of resources displayed on the dashboard.
 */
export async function getDashboardResourceCount(
  page: Page,
  resourceType: 'agents' | 'mcpservers' | 'modelapis'
): Promise<number> {
  await page.waitForLoadState('networkidle');
  
  // Look for stat cards on dashboard
  const statCard = page.locator(`[data-testid="stat-${resourceType}"]`);
  if (await statCard.isVisible()) {
    const text = await statCard.textContent();
    const match = text?.match(/\d+/);
    return match ? parseInt(match[0], 10) : 0;
  }
  
  return 0;
}
