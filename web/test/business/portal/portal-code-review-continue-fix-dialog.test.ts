import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildContinueFixPrompt,
  describeContinueFixTask,
  deriveContinueFixTaskOptions,
  findContinueFixTemplate,
  resolveContinueFixInstruction
} from '../../../src/business/portal/portal-code-review-continue-fix-dialog.tsx';
import type { CodeReviewRunDetail } from '../../../src/business/portal/code-review-types.ts';
import type { TaskItem } from '../../../src/lib/tasks.ts';

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
  fix_requests: [],
  timeline_events: []
};

const tasks: TaskItem[] = [
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
    title: 'Other repo',
    repo: 'acme/api',
    branch: 'main',
    dateLabel: '3/22',
    updatedAt: '2 分钟前',
    createdAt: '2026-03-22T08:00:00.000Z',
    status: 'completed',
    prompt: 'other'
  }
];

test('deriveContinueFixTaskOptions only returns threads for the current repository', () => {
  const result = deriveContinueFixTaskOptions(tasks, run);
  assert.deepEqual(
    result.map((task) => task.id),
    ['thread-1']
  );
});

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

test('describeContinueFixTask exposes repo branch and task status summary', () => {
  assert.equal(
    describeContinueFixTask(tasks[0]),
    'acme/web · main · Completed'
  );
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
