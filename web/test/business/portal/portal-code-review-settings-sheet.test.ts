import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildCodeReviewRepositoryEntries,
  buildAutoFixSeverityPayload,
  getCodeReviewSettingsDescription,
  readAutoFixSeverityLevels
} from '../../../src/business/portal/portal-code-review-settings-sheet.tsx';

test('auto-fix severity helpers round-trip levels payload', () => {
  assert.deepEqual(readAutoFixSeverityLevels({ levels: ['high', 'low'] }), [
    'high',
    'low'
  ]);
  assert.equal(buildAutoFixSeverityPayload([]), null);
  assert.deepEqual(buildAutoFixSeverityPayload(['medium']), {
    levels: ['medium']
  });
});

test('settings description reflects selected repository context', () => {
  assert.equal(
    getCodeReviewSettingsDescription({
      hasSelectedRepository: false,
      repositoryName: ''
    }),
    '请先在页面顶部选择一个仓库'
  );
  assert.equal(
    getCodeReviewSettingsDescription({
      hasSelectedRepository: true,
      repositoryName: 'acme/api'
    }),
    '当前仓库：acme/api'
  );
});

test('repository entries expose visible repository list and active repository state', () => {
  const entries = buildCodeReviewRepositoryEntries({
    repositories: [
      {
        id: 1,
        provider: 'github',
        external_repo_id: 'gh-1',
        full_name: 'acme/api',
        default_branch: 'main',
        review_enabled: true
      },
      {
        id: 2,
        provider: 'gitlab',
        external_repo_id: 'gl-1',
        full_name: 'acme/web',
        default_branch: 'develop',
        gitlab_base_url: 'https://gitlab.example.com',
        review_enabled: false
      },
    ],
    selectedRepositoryId: 1,
    selectedRepository: {
      id: 2,
      provider: 'gitlab',
      external_repo_id: 'gl-1',
      full_name: 'acme/web',
      default_branch: 'develop',
      gitlab_base_url: 'https://gitlab.example.com',
      review_enabled: false
    },
    enabledRepositoryIds: new Set([1])
  });

  assert.equal(entries.length, 2);
  assert.equal(entries[0]?.displayName, 'acme/api');
  assert.equal(entries[0]?.isActive, true);
  assert.equal(entries[1]?.displayName, 'acme/web');
  assert.equal(entries[1]?.defaultBranch, 'develop');
  assert.equal(entries[1]?.isActive, false);
});
