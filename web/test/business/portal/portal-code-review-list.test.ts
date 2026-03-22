import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PortalCodeReviewList } from '../../../src/business/portal/portal-code-review-list.tsx';
import type { PortalCodeReviewRunItem } from '../../../src/hooks/use-portal-code-review-state.ts';

const runs: PortalCodeReviewRunItem[] = [
  {
    id: 101,
    repository_integration_id: 1,
    provider: 'github',
    event_type: 'pull_request',
    status: 'completed',
    idempotency_key: 'gh-101',
    external_pr_or_mr_id: '42',
    head_commit_id: 'abc123456789',
    created_at: '2026-03-22T09:00:00.000Z',
    repository: {
      id: 1,
      provider: 'github',
      external_repo_id: 'repo-1',
      repository_identity_key: 'github::acme/api',
      full_name: 'acme/api'
    },
    repositoryName: 'acme/api',
    repositoryDefaultBranch: 'main',
    mode: 'pending_approval',
    hasPendingApproval: true,
    pendingApprovalCount: 2,
    findingsCount: 3,
    lastEventType: 'fix_request_created'
  }
];

const baseProps: React.ComponentProps<typeof PortalCodeReviewList> = {
  visibleRuns: runs,
  selectedRunId: 101,
  onSelectRun: () => undefined,
  searchQuery: '',
  onSearchQueryChange: () => undefined,
  statusFilter: 'all',
  onStatusFilterChange: () => undefined,
  modeFilter: 'all',
  onModeFilterChange: () => undefined,
  isLoading: false,
  isRefreshing: false,
  hasLoadedInitialData: true,
  emptyStateMessage: '当前仓库还没有审查运行',
  pendingApprovalCount: 2
};

test('PortalCodeReviewList renders toolbar filters and run metadata', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewList, baseProps)
  );

  assert.match(markup, /代码审查运行/);
  assert.match(markup, /搜索仓库、PR\/MR、提交或事件/);
  assert.match(markup, /acme\/api/);
  assert.match(markup, /PR #42/);
  assert.match(markup, /默认分支/);
  assert.match(markup, /问题 3/);
  assert.match(markup, /待审批 2/);
});

test('PortalCodeReviewList shows loading skeleton before initial data arrives', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewList, {
      ...baseProps,
      isLoading: true,
      hasLoadedInitialData: false,
      visibleRuns: []
    })
  );

  assert.match(markup, /bg-card/);
  assert.doesNotMatch(markup, /当前仓库还没有审查运行/);
});

test('PortalCodeReviewList shows filtered empty state with message', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewList, {
      ...baseProps,
      visibleRuns: [],
      searchQuery: 'missing',
      emptyStateMessage: '没有匹配条件的审查运行'
    })
  );

  assert.match(markup, /没有匹配条件的审查运行/);
});
