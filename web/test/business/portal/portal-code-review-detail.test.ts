import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFile } from 'node:fs/promises';
import { PortalCodeReviewDetail } from '../../../src/business/portal/portal-code-review-detail.tsx';
import {
  getLatestTimelineEvent,
  summarizeFixRequestStates
} from '../../../src/business/portal/portal-code-review-sidebar.tsx';
import type { CodeReviewRunDetail } from '../../../src/business/portal/code-review-types.ts';

const run: CodeReviewRunDetail = {
  id: 8,
  repository_integration_id: 2,
  provider: 'github',
  event_type: 'pull_request',
  status: 'completed',
  idempotency_key: 'detail-8',
  external_pr_or_mr_id: '88',
  head_commit_id: 'abcdef1234567890',
  created_at: '2026-03-22T10:00:00.000Z',
  repository: {
    id: 2,
    provider: 'github',
    external_repo_id: 'gh-2',
    repository_identity_key: 'github::acme/web',
    full_name: 'acme/web'
  },
  findings: [
    {
      id: 1,
      severity: 'high',
      category: 'security',
      file_path: 'src/main.ts',
      line_start: 18,
      line_end: 18,
      title: 'Unsanitized value',
      body: 'Escape this payload before render.',
      rule_id: 'security/no-unsanitized',
      can_auto_fix: true,
      metadata: null
    }
  ],
  fix_requests: [
    {
      id: 9,
      review_run_id: 8,
      review_finding_id: 1,
      source: 'auto_policy',
      status: 'running',
      approval_required: true
    }
  ],
  timeline_events: [
    {
      id: 1,
      event_type: 'review_requested',
      payload: null,
      created_at: '2026-03-22T10:00:00.000Z'
    },
    {
      id: 2,
      event_type: 'fix_request_approved',
      payload: { fix_request_id: 9, review_finding_id: 1 },
      created_at: '2026-03-22T10:00:30.000Z'
    },
    {
      id: 3,
      event_type: 'fix_request_running',
      payload: { fix_request_id: 9, runner_job_id: 'runner-9' },
      created_at: '2026-03-22T10:00:45.000Z'
    },
    {
      id: 4,
      event_type: 'analysis_completed',
      payload: { finding_count: 1 },
      created_at: '2026-03-22T10:01:00.000Z'
    }
  ]
};

test('PortalCodeReviewDetail renders findings and timeline for selected run', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: run.id,
      run,
      isLoading: false,
      errorMessage: null,
      onRetry: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: true
    })
  );

  assert.match(markup, /Unsanitized value/);
  assert.match(markup, /评审报告/);
  assert.match(markup, /修复建议/);
  assert.match(markup, /搜索文件路径/);
  assert.match(markup, /1 \/ 1/);
  assert.match(markup, /py-2 hover:no-underline/);
  assert.match(markup, /space-y-1"/);
  assert.match(markup, /flex items-center gap-2 text-left/);
  assert.match(markup, /line-clamp-1 flex-1 text-sm font-medium/);
  assert.match(markup, /line-clamp-1 text-xs text-muted-foreground/);
  assert.doesNotMatch(markup, /筛选结果/);
  assert.doesNotMatch(markup, /运行信息/);
  assert.doesNotMatch(markup, /同步审查结果/);
  assert.doesNotMatch(markup, /返回列表|返回结果列表|查看关联线程/);
});

test('PortalCodeReviewDetail renders error state when detail load fails', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: 8,
      run: null,
      isLoading: false,
      errorMessage: '加载审查详情失败，请稍后重试',
      onRetry: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: false
    })
  );

  assert.match(markup, /审查加载失败/);
  assert.match(markup, /重试/);
  assert.doesNotMatch(markup, /返回列表|返回结果列表/);
});

test('PortalCodeReviewDetail surfaces pending fix count in tab label', () => {
  const pendingRun: CodeReviewRunDetail = {
    ...run,
    fix_requests: [
      {
        id: 15,
        review_run_id: 8,
        review_finding_id: 1,
        source: 'auto_policy',
        status: 'pending_approval',
        approval_required: true
      }
    ]
  };

  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: pendingRun.id,
      run: pendingRun,
      isLoading: false,
      errorMessage: null,
      onRetry: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: true
    })
  );

  assert.match(markup, /修复建议/);
  assert.match(markup, />1</);
});

test('PortalCodeReviewDetail keeps fixes tab header lightweight in source', async () => {
  const source = await readFile(
    new URL('../../../src/business/portal/portal-code-review-detail.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /bg-card\/70/);
  assert.match(source, /待处理修复/);
  assert.doesNotMatch(source, /修复队列/);
  assert.doesNotMatch(source, /在这里处理待审批修复/);
});

test('PortalCodeReviewSidebar compact layout keeps fixes area dense in source', async () => {
  const source = await readFile(
    new URL('../../../src/business/portal/portal-code-review-sidebar.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /space-y-3/);
  assert.match(source, /gap-3 sm:flex-row sm:items-center/);
  assert.match(source, /gap-2\.5/);
});

test('PortalCodeReviewDetail renders approved fixes as queued copy', () => {
  const approvedRun: CodeReviewRunDetail = {
    ...run,
    fix_requests: [
      {
        id: 16,
        review_run_id: 8,
        review_finding_id: 1,
        source: 'auto_policy',
        status: 'approved',
        approval_required: true
      }
    ],
    timeline_events: [
      {
        id: 5,
        event_type: 'fix_request_approved',
        payload: { fix_request_id: 16, review_finding_id: 1 },
        created_at: '2026-03-22T10:02:00.000Z'
      }
    ]
  };

  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: approvedRun.id,
      run: approvedRun,
      isLoading: false,
      errorMessage: null,
      onRetry: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: true
    })
  );

  assert.match(markup, /已入队/);
});

test('PortalCodeReviewDetail renders nothing when no run is selected', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: null,
      run: null,
      isLoading: false,
      errorMessage: null,
      onRetry: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: false
    })
  );

  assert.equal(markup, '');
});

test('sidebar helpers summarize fix request states and latest event', () => {
  assert.deepEqual(summarizeFixRequestStates(run.fix_requests), {
    pending_approval: 0,
    approved: 0,
    rejected: 0,
    running: 1,
    completed: 0,
    failed: 0
  });
  assert.equal(getLatestTimelineEvent(run.timeline_events)?.event_type, 'analysis_completed');
});
