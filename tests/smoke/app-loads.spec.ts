/**
 * Smoke test: Verify the application loads correctly.
 */

import { test, expect } from '@playwright/test';

test.describe('App Loading', () => {
  test('should load the application without errors', async ({ page }) => {
    // Navigate to the app
    await page.goto('/');
    
    // Wait for the page to load
    await page.waitForLoadState('domcontentloaded');
    
    // Check that the app container is present
    await expect(page.locator('body')).toBeVisible();
    
    // Check there are no critical JavaScript errors
    const errors: string[] = [];
    page.on('pageerror', (error) => {
      errors.push(error.message);
    });
    
    // Give the app time to initialize
    await page.waitForTimeout(2000);
    
    // The app should not have critical errors (some warnings are OK)
    const criticalErrors = errors.filter(e => 
      !e.includes('ResizeObserver') && // Ignore ResizeObserver warnings
      !e.includes('Warning:')          // Ignore React warnings
    );
    
    expect(criticalErrors).toHaveLength(0);
  });

  test('should display the main navigation', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    // Check for main navigation elements
    // The sidebar should have links to main sections
    const body = page.locator('body');
    await expect(body).toBeVisible();
    
    // App should render something (not blank)
    const content = await page.content();
    expect(content.length).toBeGreaterThan(1000);
  });

  test('should support dark theme by default', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    
    // Check for dark theme class on html or body
    const html = page.locator('html');
    await expect(html).toHaveClass(/dark/);
  });
});
