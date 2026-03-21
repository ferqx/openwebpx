import { test, expect } from '@playwright/test';

test.describe('Basic Smoke Test', () => {
  test('should redirect unauthenticated users to login page', async ({ page }) => {
    // Navigate to the root path
    await page.goto('/');

    // Wait for redirect to happen
    await page.waitForURL('**/login');

    // Check if we are on the login page
    expect(page.url()).toContain('/login');

    // Verify login page elements
    const loginTitle = page.locator('h1, h2, .text-2xl', { hasText: /登录|Login/i }).first();
    await expect(loginTitle).toBeVisible();
  });

  test('login page should have required fields', async ({ page }) => {
    await page.goto('/login');

    // Check for username and password inputs by their ID or accessible labels
    const usernameInput = page.locator('#username');
    const passwordInput = page.locator('#password');
    const submitButton = page.locator('button[type="submit"]');

    await expect(usernameInput).toBeVisible();
    await expect(passwordInput).toBeVisible();
    await expect(submitButton).toBeVisible();
  });
});
