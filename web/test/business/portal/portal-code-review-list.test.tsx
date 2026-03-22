import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  PortalCodeReviewFilters,
  PortalCodeReviewList
} from '../../../src/business/portal/portal-code-review-list.tsx';
import {
  PortalCodeReviewRunCard,
  getReviewModeMeta,
  getReviewStatusMeta
} from '../../../src/business/portal/portal-code-review-run-card.tsx';
import { type PortalCodeReviewRunItem } from '../../../src/hooks/use-portal-code-review-state.ts';

const run: PortalCodeReviewRunItem = {
  id: 7,
  repository_integration_id: 1,
  provider: 'github',
  event_type: 'pull_request',
  status: 'completed',
  idempotency_key: 'run-7',
  external_pr_or_mr_id: '41',
  head_commit_id: 'abcdef123456',
  repository: {
    id: 1,
    provider: 'github',
    external_repo_id: 'gh-1',
    full_name: 'acme/api',
    default_branch: 'main'
  },
  repositoryName: 'acme/api',
  repositoryDefaultBranch: 'main',
  mode: 'pending_approval',
  hasPendingApproval: true,
  pendingApprovalCount: 2,
  findingsCount: 3,
  lastEventType: 'fix_request_created',
  created_at: '2026-03-22T09:00:00.000Z'
};

test('code review run meta helpers map status and mode to localized text', () => {
  assert.equal(getReviewStatusMeta('queued').label, '排队中');
  assert.equal(getReviewStatusMeta('completed').label, '已完成');
  assert.equal(getReviewModeMeta('pending_approval')?.label, '待审批');
  assert.equal(getReviewModeMeta('review_only')?.label, '仅审查');
});

test('PortalCodeReviewRunCard renders repository and pending approval summary', () => {
  const markup = renderToStaticMarkup(
    <PortalCodeReviewRunCard run={run} selected={false} onSelect={() => {}} />
  );

  assert.match(markup, /acme\/api/);
  assert.match(markup, /待审批 2/);
  assert.match(markup, /问题 3/);
});

test('PortalCodeReviewList renders filter panel and result summary without duplicate result section', () => {
  const filterMarkup = renderToStaticMarkup(
    <PortalCodeReviewFilters
      searchQuery=""
      onSearchQueryChange={() => {}}
      statusFilter="completed"
      onStatusFilterChange={() => {}}
      modeFilter="pending_approval"
      onModeFilterChange={() => {}}
      isLoading={false}
      isRefreshing={false}
      hasLoadedInitialData={true}
    />
  );
  const listMarkup = renderToStaticMarkup(
    <PortalCodeReviewList
      visibleRuns={[run]}
      selectedRunId={null}
      onSelectRun={() => {}}
      isLoading={false}
      isRefreshing={false}
      hasLoadedInitialData={true}
      emptyStateMessage="当前仓库还没有审查运行"
      searchQuery=""
      onSearchQueryChange={() => {}}
      statusFilter="completed"
      onStatusFilterChange={() => {}}
      modeFilter="pending_approval"
      onModeFilterChange={() => {}}
      pendingApprovalCount={2}
    />
  );

  assert.match(filterMarkup, /筛选条件/);
  assert.match(filterMarkup, /快速筛选/);
  assert.match(listMarkup, /共 1 条审查结果/);
  assert.match(listMarkup, /当前筛选：已完成 \/ 待审批/);
  assert.doesNotMatch(listMarkup, /筛选条件/);
});

test('PortalCodeReviewList renders empty state copy', () => {
  const emptyMarkup = renderToStaticMarkup(
    <PortalCodeReviewList
      visibleRuns={[]}
      selectedRunId={null}
      onSelectRun={() => {}}
      isLoading={false}
      isRefreshing={false}
      hasLoadedInitialData={true}
      emptyStateMessage="当前仓库还没有审查运行"
      searchQuery=""
      onSearchQueryChange={() => {}}
      statusFilter="all"
      onStatusFilterChange={() => {}}
      modeFilter="all"
      onModeFilterChange={() => {}}
      pendingApprovalCount={0}
    />
  );

  assert.match(emptyMarkup, /当前仓库还没有审查运行/);
  assert.match(emptyMarkup, /暂无审查结果/);
});
