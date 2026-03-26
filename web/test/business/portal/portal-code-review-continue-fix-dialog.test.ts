import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { act, create } from 'react-test-renderer';
import {
  buildContinueFixPrompt,
  PortalCodeReviewContinueFixDialog,
  findContinueFixTemplate,
  resolveContinueFixInstruction
} from '../../../src/business/portal/portal-code-review-continue-fix-dialog.tsx';
import type { CodeReviewRunDetail } from '../../../src/business/portal/code-review-types.ts';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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
  thread_id: 'thread-1',
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
  fix_requests: [],
  timeline_events: []
};

const threadTask = {
  id: 'thread-1',
  title: 'Fix web app',
  repo: 'acme/web',
  branch: 'main',
  dateLabel: '3/22',
  updatedAt: '1 分钟前',
  createdAt: '2026-03-22T09:00:00.000Z',
  status: 'completed',
  prompt: 'original'
};

type ReactNodeLike = React.ReactNode;

const getNodeText = (node: ReactNodeLike): string => {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(getNodeText).join('');
  if (!React.isValidElement(node)) return '';
  return getNodeText(node.props.children);
};

const renderDialog = (
  props: React.ComponentProps<typeof PortalCodeReviewContinueFixDialog>
) => {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(React.createElement(PortalCodeReviewContinueFixDialog, props));
  });
  if (!renderer) {
    throw new Error('failed to render dialog');
  }
  return renderer;
};

const getDialogContentTree = (renderer: ReturnType<typeof create>) => {
  const dialogContent = renderer.root.find(
    (node) => typeof node.type === 'function' && node.type.name === 'DialogContent'
  );
  return dialogContent.props.children as ReactNodeLike;
};

const getDialogFooterButtons = (renderer: ReturnType<typeof create>) => {
  const dialogContent = renderer.root.find(
    (node) => typeof node.type === 'function' && node.type.name === 'DialogContent'
  );
  const children = Array.isArray(dialogContent.props.children)
    ? dialogContent.props.children
    : [dialogContent.props.children];
  const dialogFooter = children.find(
    (child) =>
      React.isValidElement(child) &&
      typeof child.type === 'function' &&
      child.type.name === 'DialogFooter'
  );
  const footerChildren = dialogFooter
    ? Array.isArray(dialogFooter.props.children)
      ? dialogFooter.props.children
      : [dialogFooter.props.children]
    : [];
  return footerChildren.filter(React.isValidElement);
};

test('buildContinueFixPrompt includes instruction and findings summary', () => {
  const prompt = buildContinueFixPrompt({
    run,
    instruction: '请继续修复这次审查发现的问题。'
  });

  assert.match(prompt, /请继续修复这次审查发现的问题。/);
  assert.match(prompt, /仓库: acme\/web/);
  assert.match(prompt, /审查发现:/);
  assert.match(prompt, /\[high\] Unsanitized value/);
  assert.match(prompt, /src\/main.ts:18/);
});

test('continue-fix template helpers resolve defaults and custom values', () => {
  assert.equal(
    findContinueFixTemplate(
      '请根据本次代码审查结果修复问题，优先处理高优先级项，并在完成后说明修改内容。'
    ),
    'balanced'
  );
  assert.equal(findContinueFixTemplate('something custom'), 'custom');
  assert.match(resolveContinueFixInstruction('strict'), /逐项修复问题/);
  assert.equal(resolveContinueFixInstruction('missing'), '');
});

test('continue-fix prompt preview includes task-relevant review context', () => {
  const prompt = buildContinueFixPrompt({
    run,
    instruction:
      '请根据本次代码审查结果修复问题，优先处理高优先级项，并在完成后说明修改内容。'
  });

  assert.match(prompt, /运行: #8/);
  assert.match(prompt, /类型: pull_request/);
  assert.match(prompt, /说明: Escape this payload before render\./);
});

test('continue-fix dialog disables submit when no bound thread exists', () => {
  const renderer = renderDialog({
    open: true,
    onOpenChange: () => {},
    run,
    threadId: null,
    threadTask: null,
    instruction: '请根据本次代码审查结果修复问题。',
    onInstructionChange: () => {},
    isSubmitting: false,
    onSubmit: () => {}
  });

  const [, submitButton] = getDialogFooterButtons(renderer);

  assert.equal(typeof submitButton?.type === 'function' ? submitButton.type.name : '', 'Button');
  assert.equal(submitButton?.props.disabled, true);
});

test('continue-fix dialog submit button invokes the passed onSubmit handler', () => {
  let submitCount = 0;
  const renderer = renderDialog({
    open: true,
    onOpenChange: () => {},
    run,
    threadId: 'thread-1',
    threadTask,
    instruction: '请根据本次代码审查结果修复问题。',
    onInstructionChange: () => {},
    isSubmitting: false,
    onSubmit: () => {
      submitCount += 1;
    }
  });

  const [, submitButton] = getDialogFooterButtons(renderer);
  assert.equal(typeof submitButton?.type === 'function' ? submitButton.type.name : '', 'Button');
  assert.equal(submitButton?.props.disabled, false);

  act(() => {
    submitButton?.props.onClick();
  });

  assert.equal(submitCount, 1);
});

test('continue-fix dialog renders the bound thread as read-only contextual info', () => {
  const renderer = renderDialog({
    open: true,
    onOpenChange: () => {},
    run,
    threadId: 'thread-1',
    threadTask: null,
    instruction: '请根据本次代码审查结果修复问题。',
    onInstructionChange: () => {},
    isSubmitting: false,
    onSubmit: () => {}
  });

  const renderedText = getNodeText(getDialogContentTree(renderer));

  assert.match(renderedText, /绑定线程/);
  assert.match(renderedText, /线程 thread-1/);
  assert.match(renderedText, /该线程尚未加载到本地任务列表/);
  assert.doesNotMatch(renderedText, /选择目标线程/);
});
