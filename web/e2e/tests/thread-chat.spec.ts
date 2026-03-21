import { test, expect } from '@playwright/test';
import { doMockLogin } from '../utils/auth-mock';

test.describe('Complete Task Lifecycle Flow', () => {
  const MOCK_THREAD_ID = 'thread-live-test-123';

  test('should create a task from portal and perform a successful chat interaction', async ({ page }) => {
    // 1. SETUP ROUTES
    await page.route('**/api/integrations/scm/connections', async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ connections: [{ provider: 'github', connection_key: 'github-key', expired: false }] }) });
    });

    await page.route('**/api/integrations/scm/connection/validate', async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ valid: true }) });
    });

    await page.route('**/api/integrations/scm/repositories*', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          repositories: [{ id: 'repo-1', fullName: 'test-user/app', source: { key: 'github-key' }, defaultBranch: 'main' }]
        })
      });
    });

    await page.route('**/api/integrations/scm/branches*', async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ branches: ['main'] }) });
    });

    await page.route('**/api/threads', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({ status: 200, body: JSON.stringify({ thread_id: MOCK_THREAD_ID, metadata: {} }) });
      } else {
        await route.fulfill({ status: 200, body: JSON.stringify([]) });
      }
    });

    await page.route('**/api/runs/stream', async (route) => {
      const sse = `event: bootstrap_snapshot\ndata: {"status": "success", "accepted": true}\n\n`;
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse });
    });

    await page.route(new RegExp(`/api/threads/${MOCK_THREAD_ID}/state`), async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          values: {
            messages: [
              { type: 'human', content: 'Initial user prompt', id: 'm1' },
              { type: 'ai', content: 'Ready.', id: 'm2' }
            ]
          },
          checkpoint: { thread_id: MOCK_THREAD_ID }
        })
      });
    });

    await page.route(new RegExp(`/api/threads/${MOCK_THREAD_ID}/runs/stream`), async (route) => {
      const sse = [
        `event: values\ndata: {"messages": [{"type": "ai", "content": "Updated.", "id": "m3"}]}\n\n`,
        `event: values\ndata: {"messages": [{"type": "ai", "content": "Updated.", "id": "m3", "tool_calls": [{"name": "apply_patch", "args": {"patch": "--- a/i.ts\\n+++ b/i.ts\\n@@ -1,1 +1,1 @@\\n-old\\n+new", "path": "i.ts"}, "id": "tc1"}]}]}\n\n`,
        `event: end\ndata: {}\n\n`
      ].join('');
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: sse });
    });

    // 2. START FLOW
    await doMockLogin(page);

    // Portal actions
    await page.getByLabel('选择仓库').click();
    await expect(page.locator('[data-slot="command-item"]').first()).toBeVisible({ timeout: 15000 });
    await page.locator('[data-slot="command-item"]').first().click();

    await page.getByLabel('选择分支').click();
    await expect(page.locator('[data-slot="command-item"]').first()).toBeVisible({ timeout: 10000 });
    await page.locator('[data-slot="command-item"]').first().click();

    await page.locator('textarea[placeholder*="任务" i]').first().fill('Initial user prompt');
    await page.locator('button[type="submit"]').click();

    // Verify Redirect
    await page.waitForURL(`**/tasks/${MOCK_THREAD_ID}`, { timeout: 20000 });

    // Chat actions
    await expect(page.getByText('Initial user prompt').first()).toBeVisible({ timeout: 15000 });

    await page.locator('textarea[placeholder*="任务" i]').first().fill('Please update');
    await page.locator('button[type="submit"]').click();

    // Verify Output
    await expect(page.getByText('Updated.').first()).toBeVisible({ timeout: 20000 });
    await expect(page.getByText('i.ts').first()).toBeVisible();
  });
});
