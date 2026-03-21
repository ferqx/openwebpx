import { test, expect } from '@playwright/test';
import { doMockLogin } from '../utils/auth-mock';

test.describe('Portal (Main Page) Interaction', () => {
  test('should allow selecting a repository and branch to start a task', async ({ page }) => {
    // 1. SETUP ALL ROUTES FIRST - before any navigation
    await page.route('**/api/integrations/scm/connections', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          connections: [
            { provider: 'github', connection_key: 'github-key', expired: false, has_refresh_token: true }
          ]
        })
      });
    });

    await page.route('**/api/integrations/scm/connection/validate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ valid: true, revoked: false })
      });
    });

    await page.route('**/api/integrations/scm/repositories*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          repositories: [
            {
              id: 'repo-1',
              fullName: 'test-user/my-awesome-app',
              defaultBranch: 'main',
              source: { key: 'github-key', provider: 'github' }
            }
          ]
        })
      });
    });

    await page.route('**/api/integrations/scm/branches*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ branches: ['main', 'feature/login'] })
      });
    });

    await page.route('**/api/threads', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ thread_id: 'new-thread-999', metadata: {} })
        });
      }
    });

    await page.route('**/api/runs/stream', async (route) => {
      const sseContent = `event: bootstrap_snapshot\ndata: {"status": "success", "accepted": true}\n\n`;
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseContent });
    });

    // 2. NOW LOGIN (triggers the initial requests)
    await doMockLogin(page);

    // 3. INTERACT
    // Wait for the repo picker to be clickable (means connections loaded)
    // Phase 1: Select repository
    const repoPicker = page.getByLabel('选择仓库');
    await expect(repoPicker).toBeVisible();
    await repoPicker.click();

    // Wait for at least one command item to be visible in the list
    const firstRepoItem = page.locator('[data-slot="command-item"]').first();
    await expect(firstRepoItem).toBeVisible({ timeout: 15000 });
    await firstRepoItem.click();

    // Phase 2: Select branch
    const branchPicker = page.getByLabel('选择分支');
    await expect(branchPicker).toBeVisible();
    await branchPicker.click();

    // Wait for at least one branch item to be visible
    const firstBranchItem = page.locator('[data-slot="command-item"]').first();
    await expect(firstBranchItem).toBeVisible({ timeout: 10000 });
    await firstBranchItem.click();
    // Input prompt and Submit
    const promptInput = page.locator('textarea[placeholder*="任务" i], textarea[placeholder*="需求" i]').first();
    await promptInput.fill('E2E Test task');

    const submitButton = page.locator('button[type="submit"]');
    await expect(submitButton).toBeEnabled();
    await submitButton.click();

    // Verify redirection
    await page.waitForURL('**/tasks/new-thread-999', { timeout: 20000 });
    expect(page.url()).toContain('/tasks/new-thread-999');
  });

  test('should show disabled state when no repo is selected', async ({ page }) => {
    await doMockLogin(page);
    const submitButton = page.locator('button[type="submit"]');
    await expect(submitButton).toBeDisabled();
    await expect(page.getByText('请选择仓库后再发送')).toBeVisible();
  });
});
