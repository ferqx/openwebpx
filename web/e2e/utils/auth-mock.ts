import { type Page } from '@playwright/test';

export const REAL_AUTH_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ4eDI5MTE4MDc4MiIsInJvbGUiOiJkZXZlbG9wZXIiLCJ0ZWFtX2lkIjoieHgyOTExODA3ODIiLCJkaXNwbGF5X25hbWUiOiJVc2VyIHh4MjkxMTgwNzgyIiwiZW1haWwiOiJ4eDI5MTE4MDc4MkBleGFtcGxlLmNvbSIsImlhdCI6MTc3MzA2ODYxMiwiZXhwIjoxNzc1NjYwNjEyfQ.nE_-AsO2dBfJL0C8pJLg2Ksi-aHX9m7cFDcBb6byGMc';

export async function doMockLogin(page: Page, redirectPath: string = '/') {
  // 1. Setup minimal Auth and Config mocks that every page needs
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ identity: 'xx291180782', display_name: 'User xx291180782', is_authenticated: true })
    });
  });

  await page.route('**/api/integrations/code-review/settings', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, settings: {} }) });
  });

  // 2. Inject token
  await page.addInitScript((token) => {
    window.localStorage.setItem('sandbox-agent:auth-token', token);
  }, REAL_AUTH_TOKEN);

  // 3. Navigate to target - THIS STARTS THE APP
  await page.goto(redirectPath);

  // 4. Ensure token is set in the session
  await page.evaluate((token) => {
    window.localStorage.setItem('sandbox-agent:auth-token', token);
  }, REAL_AUTH_TOKEN);

  await page.waitForLoadState('domcontentloaded');
}
