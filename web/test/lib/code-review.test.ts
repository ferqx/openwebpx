import test from 'node:test';
import assert from 'node:assert/strict';
import type {
  CodeReviewTrigger,
  CodeReviewAutoReview,
  CodeReviewProvider,
  CodeReviewGlobalSettings,
  CodeReviewRepositorySetting,
  CodeReviewWebhookSyncResult
} from '../../src/lib/code-review.ts';

test('CodeReviewTrigger type accepts valid values', () => {
  const prOpen: CodeReviewTrigger = 'pr_open';
  const push: CodeReviewTrigger = 'push';
  assert.equal(prOpen, 'pr_open');
  assert.equal(push, 'push');
});

test('CodeReviewAutoReview type accepts valid values', () => {
  const followGlobal: CodeReviewAutoReview = 'follow_global';
  const enabled: CodeReviewAutoReview = 'enabled';
  const disabled: CodeReviewAutoReview = 'disabled';
  assert.equal(followGlobal, 'follow_global');
  assert.equal(enabled, 'enabled');
  assert.equal(disabled, 'disabled');
});

test('CodeReviewProvider type accepts valid values', () => {
  const github: CodeReviewProvider = 'github';
  const gitlab: CodeReviewProvider = 'gitlab';
  assert.equal(github, 'github');
  assert.equal(gitlab, 'gitlab');
});

test('CodeReviewGlobalSettings structure is correct', () => {
  const settings: CodeReviewGlobalSettings = {
    autoReviewEnabled: true,
    defaultTrigger: 'pr_open',
    updatedAt: Date.now(),
    updatedBy: 'user123'
  };

  assert.equal(typeof settings.autoReviewEnabled, 'boolean');
  assert.equal(typeof settings.defaultTrigger, 'string');
  assert.equal(typeof settings.updatedAt, 'number');
  assert.equal(typeof settings.updatedBy, 'string');
});

test('CodeReviewRepositorySetting structure is correct', () => {
  const setting: CodeReviewRepositorySetting = {
    provider: 'github',
    repository: 'owner/repo',
    gitlabBaseUrl: undefined,
    autoReview: 'follow_global',
    trigger: 'pr_open',
    updatedAt: Date.now(),
    updatedBy: 'user123'
  };

  assert.equal(setting.provider, 'github');
  assert.equal(setting.repository, 'owner/repo');
  assert.equal(setting.gitlabBaseUrl, undefined);
  assert.equal(setting.autoReview, 'follow_global');
  assert.equal(setting.trigger, 'pr_open');
});

test('CodeReviewRepositorySetting works with GitLab', () => {
  const setting: CodeReviewRepositorySetting = {
    provider: 'gitlab',
    repository: 'group/project',
    gitlabBaseUrl: 'https://gitlab.company.com',
    autoReview: 'enabled',
    trigger: 'push',
    updatedAt: 1234567890,
    updatedBy: 'admin'
  };

  assert.equal(setting.provider, 'gitlab');
  assert.equal(setting.gitlabBaseUrl, 'https://gitlab.company.com');
  assert.equal(setting.autoReview, 'enabled');
  assert.equal(setting.trigger, 'push');
});

test('CodeReviewWebhookSyncResult structure is correct', () => {
  const result: CodeReviewWebhookSyncResult = {
    enabled: true,
    ok: true,
    mode: 'auto',
    message: 'Webhook synchronized successfully',
    provider: 'github',
    repository: 'owner/repo',
    webhookUrl: 'https://api.example.com/webhooks/github'
  };

  assert.equal(result.enabled, true);
  assert.equal(result.ok, true);
  assert.equal(result.mode, 'auto');
  assert.equal(result.message, 'Webhook synchronized successfully');
  assert.equal(result.provider, 'github');
  assert.equal(result.repository, 'owner/repo');
  assert.equal(result.webhookUrl, 'https://api.example.com/webhooks/github');
});

test('CodeReviewWebhookSyncResult works with manual mode', () => {
  const result: CodeReviewWebhookSyncResult = {
    enabled: true,
    ok: true,
    mode: 'manual',
    message: 'Please configure webhook manually',
    provider: 'gitlab',
    repository: 'group/project',
    webhookUrl: undefined,
    manualSetup: {
      provider: 'gitlab',
      repository: 'group/project',
      events: ['push', 'merge_request'],
      payloadUrl: 'https://api.example.com/webhooks/gitlab',
      secret: 'webhook-secret-123',
      hint: 'Add this webhook in your GitLab project settings'
    }
  };

  assert.equal(result.mode, 'manual');
  assert.ok(result.manualSetup);
  assert.equal(result.manualSetup.provider, 'gitlab');
  assert.equal(result.manualSetup.events?.length, 2);
  assert.equal(result.manualSetup.secret, 'webhook-secret-123');
});
