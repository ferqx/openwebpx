import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
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
      onBack: () => undefined,
      onPublishRun: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: true
    })
  );

  assert.match(markup, /acme\/web/);
  assert.match(markup, /返回结果列表/);
  assert.match(markup, /Unsanitized value/);
  assert.match(markup, /审查已请求/);
  assert.match(markup, /分析完成/);
  assert.match(markup, /运行摘要/);
  assert.match(markup, /待处理事项/);
  assert.match(markup, /最近事件 分析完成/);
  assert.match(markup, /执行中/);
  assert.match(markup, /修复请求/);
});

test('PortalCodeReviewDetail renders error state when detail load fails', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: 8,
      run: null,
      isLoading: false,
      errorMessage: '加载审查详情失败，请稍后重试',
      onRetry: () => undefined,
      onBack: () => undefined,
      onPublishRun: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: false
    })
  );

  assert.match(markup, /审查详情加载失败/);
  assert.match(markup, /返回结果列表/);
  assert.match(markup, /重试/);
});

test('PortalCodeReviewDetail renders approval actions for pending fix requests', () => {
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
      onBack: () => undefined,
      onPublishRun: () => undefined,
      onContinueFix: () => undefined,
      onApproveFixRequest: () => undefined,
      onRejectFixRequest: () => undefined,
      canContinueFix: true
    })
  );

  assert.match(markup, /Approve/);
  assert.match(markup, /Reject/);
  assert.match(markup, /待审批/);
});

test('PortalCodeReviewDetail renders nothing when no run is selected', () => {
  const markup = renderToStaticMarkup(
    React.createElement(PortalCodeReviewDetail, {
      selectedRunId: null,
      run: null,
      isLoading: false,
      errorMessage: null,
      onRetry: () => undefined,
      onBack: () => undefined,
      onPublishRun: () => undefined,
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
