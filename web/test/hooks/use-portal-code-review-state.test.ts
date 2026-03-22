import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildCodeReviewSyncRequest,
  getPendingApprovalCount,
  deriveCodeReviewPrefetchRunIds,
  deriveVisibleCodeReviewRuns,
  getCodeReviewEmptyStateMessage,
  inferFixRequestStates,
  loadPortalCodeReviewSnapshot,
  matchesCodeReviewRepositoryContext,
  resolvePortalCodeReviewMode
} from '../../src/hooks/use-portal-code-review-state.ts';
import {
  type CodeReviewRepositorySummary,
  type CodeReviewRunDetail,
  type CodeReviewRunSummary
} from '../../src/business/portal/code-review-types.ts';

const repositories: CodeReviewRepositorySummary[] = [
  {
    id: 1,
    provider: 'github',
    external_repo_id: 'gh-1',
    full_name: 'acme/api',
    default_branch: 'main'
  },
  {
    id: 2,
    provider: 'gitlab',
    external_repo_id: 'gl-1',
    full_name: 'acme/web',
    gitlab_base_url: 'https://gitlab.example.com'
  }
];

const runs: CodeReviewRunSummary[] = [
  {
    id: 10,
    repository_integration_id: 1,
    provider: 'github',
    event_type: 'pull_request',
    status: 'completed',
    idempotency_key: 'gh-run',
    external_pr_or_mr_id: '42',
    created_at: '2026-03-22T09:00:00.000Z'
  },
  {
    id: 20,
    repository_integration_id: 2,
    provider: 'gitlab',
    event_type: 'merge_request',
    status: 'queued',
    idempotency_key: 'gl-run',
    external_pr_or_mr_id: '108',
    created_at: '2026-03-22T08:00:00.000Z'
  }
];

const githubDetail: CodeReviewRunDetail = {
  ...runs[0],
  repository: {
    id: 1,
    provider: 'github',
    external_repo_id: 'gh-1',
    repository_identity_key: 'github::acme/api',
    full_name: 'acme/api'
  },
  findings: [
    {
      id: 100,
      severity: 'high',
      category: 'security',
      file_path: 'src/app.ts',
      line_start: 12,
      line_end: 12,
      title: 'Unsafe input',
      body: 'Sanitize the value.',
      can_auto_fix: true,
      metadata: null
    }
  ],
  fix_requests: [
    {
      id: 501,
      review_run_id: 10,
      review_finding_id: 100,
      source: 'auto_policy',
      status: 'pending_approval',
      approval_required: true
    }
  ],
  timeline_events: [
    {
      id: 1,
      event_type: 'fix_request_created',
      dedupe_key: '10:created',
      payload: { fix_request_id: 501 }
    }
  ]
};

const gitlabDetail: CodeReviewRunDetail = {
  ...runs[1],
  repository: {
    id: 2,
    provider: 'gitlab',
    external_repo_id: 'gl-1',
    repository_identity_key: 'gitlab::https://gitlab.example.com::acme/web',
    full_name: 'acme/web',
    gitlab_base_url: 'https://gitlab.example.com'
  },
  findings: [],
  fix_requests: [],
  timeline_events: []
};

test('matchesCodeReviewRepositoryContext respects repo name and provider context', () => {
  assert.equal(
    matchesCodeReviewRepositoryContext(repositories[0], {
      selectedRepo: 'acme/api',
      selectedProvider: 'github'
    }),
    true
  );
  assert.equal(
    matchesCodeReviewRepositoryContext(repositories[1], {
      selectedRepo: 'acme/web',
      selectedProvider: 'gitlab_enterprise',
      selectedGitlabBaseUrl: 'https://gitlab.example.com/'
    }),
    true
  );
  assert.equal(
    matchesCodeReviewRepositoryContext(repositories[1], {
      selectedRepo: 'acme/web',
      selectedProvider: 'github'
    }),
    false
  );
});

test('buildCodeReviewSyncRequest maps SCM context to backend sync payload', () => {
  assert.deepEqual(
    buildCodeReviewSyncRequest({
      selectedRepo: 'acme/api',
      selectedProvider: 'github'
    }),
    {
      provider: 'github',
      gitlab_base_url: null
    }
  );
  assert.deepEqual(
    buildCodeReviewSyncRequest({
      selectedRepo: 'acme/web',
      selectedProvider: 'gitlab_enterprise',
      selectedGitlabBaseUrl: 'https://gitlab.example.com'
    }),
    {
      provider: 'gitlab',
      gitlab_base_url: 'https://gitlab.example.com'
    }
  );
  assert.equal(
    buildCodeReviewSyncRequest({
      selectedRepo: '',
      selectedProvider: undefined
    }),
    null
  );
});

test('inferFixRequestStates and resolvePortalCodeReviewMode derive pending approval from timeline', () => {
  const states = inferFixRequestStates(githubDetail.timeline_events);
  assert.equal(states.get(501), 'pending_approval');
  assert.equal(resolvePortalCodeReviewMode(githubDetail), 'pending_approval');
  assert.equal(getPendingApprovalCount(githubDetail), 1);
  assert.equal(resolvePortalCodeReviewMode(gitlabDetail), 'review_only');
});

test('deriveVisibleCodeReviewRuns joins repositories, filters by selected context, and promotes pending approvals', () => {
  const visible = deriveVisibleCodeReviewRuns({
    runs,
    repositories,
    runDetailsById: {
      10: githubDetail,
      20: gitlabDetail
    },
    context: {
      selectedRepo: 'acme/api',
      selectedProvider: 'github'
    },
    statusFilter: 'all',
    modeFilter: 'all',
    searchQuery: ''
  });

  assert.equal(visible.length, 1);
  assert.equal(visible[0]?.id, 10);
  assert.equal(visible[0]?.hasPendingApproval, true);
  assert.equal(visible[0]?.pendingApprovalCount, 1);
  assert.equal(visible[0]?.findingsCount, 1);
});

test('deriveVisibleCodeReviewRuns applies mode and text filters', () => {
  const visible = deriveVisibleCodeReviewRuns({
    runs,
    repositories,
    runDetailsById: {
      10: githubDetail,
      20: gitlabDetail
    },
    context: {
      selectedRepo: 'acme/web',
      selectedProvider: 'gitlab_enterprise',
      selectedGitlabBaseUrl: 'https://gitlab.example.com'
    },
    statusFilter: 'queued',
    modeFilter: 'review_only',
    searchQuery: '108'
  });

  assert.equal(visible.length, 1);
  assert.equal(visible[0]?.id, 20);
  assert.equal(visible[0]?.mode, 'review_only');
});

test('deriveCodeReviewPrefetchRunIds ignores mode resolution gaps so filtered runs can still load details', () => {
  const prefetchRunIds = deriveCodeReviewPrefetchRunIds({
    runs,
    repositories,
    runDetailsById: {},
    loadingDetailIds: {},
    context: {
      selectedRepo: 'acme/api',
      selectedProvider: 'github'
    },
    statusFilter: 'all',
    searchQuery: ''
  });

  assert.deepEqual(prefetchRunIds, [10]);
});

test('getCodeReviewEmptyStateMessage handles loading, missing repo, and filtered empty states', () => {
  assert.equal(
    getCodeReviewEmptyStateMessage({
      hasSelectedRepository: true,
      hasLoadedInitialData: false,
      hasRepositories: true,
      visibleRunCount: 0,
      hasFilters: false
    }),
    '正在加载审查运行...'
  );
  assert.equal(
    getCodeReviewEmptyStateMessage({
      hasSelectedRepository: false,
      hasLoadedInitialData: true,
      hasRepositories: true,
      visibleRunCount: 0,
      hasFilters: false
    }),
    '请选择仓库后查看代码审查'
  );
  assert.equal(
    getCodeReviewEmptyStateMessage({
      hasSelectedRepository: true,
      hasLoadedInitialData: true,
      hasRepositories: true,
      visibleRunCount: 0,
      hasFilters: true
    }),
    '没有匹配条件的审查运行'
  );
});

test('loadPortalCodeReviewSnapshot loads repositories and runs together', async () => {
  let repositoryCalls = 0;
  let runCalls = 0;

  const snapshot = await loadPortalCodeReviewSnapshot({
    listRepositories: async () => {
      repositoryCalls += 1;
      return repositories;
    },
    listRuns: async () => {
      runCalls += 1;
      return runs;
    }
  });

  assert.equal(repositoryCalls, 1);
  assert.equal(runCalls, 1);
  assert.deepEqual(snapshot, { repositories, runs });
});
