import test from 'node:test';
import assert from 'node:assert/strict';
import React, { useEffect } from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { type NavigateFunction } from 'react-router-dom';
import { usePortalCodeReviewContinuation } from '../../src/hooks/use-portal-code-review-continuation.ts';
import { type CodeReviewRunDetail } from '../../src/business/portal/code-review-types.ts';
import { type TaskItem } from '../../src/lib/tasks.ts';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type ContinuationProps = Parameters<typeof usePortalCodeReviewContinuation>[0];
type ContinuationSnapshot = ReturnType<typeof usePortalCodeReviewContinuation>;
type NavigateCall = {
  to: string;
  state: {
    initialPrompt: string;
    shouldAutoRun: boolean;
    portalTab: 'review' | 'tasks';
    task?: TaskItem;
  };
};

const makeRun = (overrides: Partial<CodeReviewRunDetail> = {}): CodeReviewRunDetail =>
  ({
    id: 8,
    repository_integration_id: 2,
    provider: 'github',
    event_type: 'pull_request',
    status: 'completed',
    idempotency_key: 'detail-8',
    external_pr_or_mr_id: '88',
    head_commit_id: 'abcdef1234567890',
    thread_id: 'thread-1',
    created_at: '2026-03-22T10:00:00.000Z',
    repository: null,
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
    fix_requests: [],
    timeline_events: [],
    ...overrides
  }) as CodeReviewRunDetail;

const makeTasks = (): TaskItem[] => [
  {
    id: 'thread-1',
    title: 'Fix web app',
    repo: 'acme/web',
    branch: 'main',
    dateLabel: '3/22',
    updatedAt: '1 分钟前',
    createdAt: '2026-03-22T09:00:00.000Z',
    status: 'completed',
    prompt: 'original'
  },
  {
    id: 'thread-2',
    title: 'Other task',
    repo: 'acme/api',
    branch: 'main',
    dateLabel: '3/22',
    updatedAt: '2 分钟前',
    createdAt: '2026-03-22T08:00:00.000Z',
    status: 'completed',
    prompt: 'other'
  }
];

const renderContinuationHook = (initialProps: ContinuationProps) => {
  let current: ContinuationSnapshot | null = null;

  const Harness = (props: ContinuationProps) => {
    const snapshot = usePortalCodeReviewContinuation(props);
    useEffect(() => {
      current = snapshot;
    }, [snapshot]);
    return null;
  };

  let renderer: ReactTestRenderer | null = null;
  act(() => {
    renderer = create(React.createElement(Harness, initialProps));
  });

  if (renderer === null || current === null) {
    throw new Error('failed to render continuation hook');
  }

  return {
    get current() {
      if (!current) {
        throw new Error('hook snapshot unavailable');
      }
      return current;
    },
    update(nextProps: ContinuationProps) {
      act(() => {
        renderer?.update(React.createElement(Harness, nextProps));
      });
    },
    unmount() {
      act(() => {
        renderer?.unmount();
      });
    }
  };
};

test('continuation stays pinned to the opened run even if selectedRun changes', async () => {
  const runOne = makeRun({
    id: 8,
    thread_id: 'thread-1',
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
    ]
  });
  const runTwo = makeRun({
    id: 9,
    thread_id: 'thread-2',
    findings: [
      {
        id: 2,
        severity: 'medium',
        category: 'quality',
        file_path: 'src/other.ts',
        line_start: 7,
        line_end: 7,
        title: 'Alternate run',
        body: 'Different run.',
        rule_id: 'quality/no-alt',
        can_auto_fix: true,
        metadata: null
      }
    ]
  });
  const tasks = makeTasks();
  const navigateCalls: NavigateCall[] = [];
  const navigate: NavigateFunction = ((to: string | number, options?: { state?: unknown }) => {
    assert.equal(typeof to, 'string');
    navigateCalls.push({
      to,
      state: options?.state as NavigateCall['state']
    });
  }) as NavigateFunction;

  const harness = renderContinuationHook({
    tasks,
    selectedRun: runOne,
    tab: 'review',
    navigate
  });

  assert.equal(harness.current.canContinueCodeReviewFix, true);

  act(() => {
    harness.current.handleOpenContinueFix(runOne);
  });

  harness.update({
    tasks,
    selectedRun: runTwo,
    tab: 'review',
    navigate
  });

  assert.equal(harness.current.codeReviewContinueFixDialogProps.run?.id, 8);
  assert.equal(harness.current.codeReviewContinueFixDialogProps.threadId, 'thread-1');

  await act(async () => {
    await harness.current.codeReviewContinueFixDialogProps.onSubmit();
  });

  assert.equal(navigateCalls.length, 1);
  assert.equal(navigateCalls[0]?.to, '/tasks/thread-1');
  assert.equal(navigateCalls[0]?.state.portalTab, 'review');
  assert.equal(navigateCalls[0]?.state.shouldAutoRun, true);
  assert.equal(navigateCalls[0]?.state.task?.id, 'thread-1');
  assert.match(navigateCalls[0]?.state.initialPrompt ?? '', /运行: #8/);

  harness.unmount();
});

test('continuation navigates to the bound thread even when metadata is not loaded locally', async () => {
  const run = makeRun({
    id: 12,
    thread_id: 'thread-12',
    findings: [
      {
        id: 3,
        severity: 'high',
        category: 'security',
        file_path: 'src/missing.ts',
        line_start: 3,
        line_end: 3,
        title: 'Missing task metadata',
        body: 'Thread exists but is not in the loaded task list.',
        rule_id: 'security/no-missing',
        can_auto_fix: true,
        metadata: null
      }
    ]
  });
  const tasks = makeTasks().filter((task) => task.id !== 'thread-1');
  const navigateCalls: NavigateCall[] = [];
  const navigate: NavigateFunction = ((to: string | number, options?: { state?: unknown }) => {
    assert.equal(typeof to, 'string');
    navigateCalls.push({
      to,
      state: options?.state as NavigateCall['state']
    });
  }) as NavigateFunction;

  const harness = renderContinuationHook({
    tasks,
    selectedRun: run,
    tab: 'review',
    navigate
  });

  act(() => {
    harness.current.handleOpenContinueFix(run);
  });

  assert.equal(harness.current.codeReviewContinueFixDialogProps.threadTask, null);

  await act(async () => {
    await harness.current.codeReviewContinueFixDialogProps.onSubmit();
  });

  assert.equal(navigateCalls.length, 1);
  assert.equal(navigateCalls[0]?.to, '/tasks/thread-12');
  assert.equal(navigateCalls[0]?.state.portalTab, 'review');
  assert.equal(navigateCalls[0]?.state.shouldAutoRun, true);
  assert.equal(navigateCalls[0]?.state.task, undefined);

  harness.unmount();
});

test('continuation is disabled when the selected run has no thread_id', () => {
  const run = makeRun({
    thread_id: null
  });
  const tasks = makeTasks();
  const navigate: NavigateFunction = (() => {}) as NavigateFunction;

  const harness = renderContinuationHook({
    tasks,
    selectedRun: run,
    tab: 'review',
    navigate
  });

  assert.equal(harness.current.canContinueCodeReviewFix, false);

  harness.unmount();
});
