import { expect, type Page, test as base } from '@playwright/test';
import { mockKubernetesApi, VISUAL_K8S_BASE, VISUAL_NAMESPACE } from './mock-k8s';

type VisualScenario = 'populated' | 'empty';
type VisualTheme = 'dark' | 'light';

export const test = base;

export async function setupVisualPage(
  page: Page,
  options: { path?: string; scenario?: VisualScenario; theme?: VisualTheme } = {}
) {
  const {
    path = '/',
    scenario = 'populated',
    theme = 'dark',
  } = options;

  await mockKubernetesApi(page, scenario);
  await page.addInitScript(({ selectedTheme }) => {
    const fixedTime = '12:00:00 PM';
    const fixedDateTime = '1/15/2025, 12:00:00 PM';

    localStorage.clear();
    localStorage.setItem('theme', selectedTheme);
    localStorage.setItem('autoRefreshEnabled', 'false');
    localStorage.setItem('autoRefreshInterval', '0');
    localStorage.setItem('kaos-system-namespace', 'kaos-visual');
    Math.random = () => 0.424242;
    Date.prototype.toLocaleTimeString = () => fixedTime;
    Date.prototype.toLocaleString = () => fixedDateTime;
  }, { selectedTheme: theme });

  const separator = path.includes('?') ? '&' : '?';
  await page.goto(`${path}${separator}kubernetesUrl=${encodeURIComponent(VISUAL_K8S_BASE)}&namespace=${VISUAL_NAMESPACE}`);
  await page.waitForLoadState('networkidle');
  await page.locator('#root').waitFor({ state: 'attached' });
  await expect(page.locator('body')).not.toContainText('TypeError');
}

export async function screenshot(page: Page, name: string, options: { fullPage?: boolean } = {}) {
  await page.waitForLoadState('networkidle');
  await expect(page).toHaveScreenshot(name, {
    fullPage: options.fullPage ?? false,
  });
}

export async function navigateToTab(page: Page, testId: string) {
  await page.getByTestId(testId).click();
  await page.waitForLoadState('networkidle');
}
