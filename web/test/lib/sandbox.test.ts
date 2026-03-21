import test from 'node:test';
import assert from 'node:assert/strict';
import type {
  SandboxInitializeStepStatus,
  SandboxInitializeStep,
  SandboxInitializeResult,
  SandboxBootstrapStatus,
  SandboxBootstrapLog,
  SandboxBootstrapResult,
  SandboxThreadCancelAction,
  SandboxThreadCancelResult,
  SandboxBootstrapEvent,
  SandboxBootstrapStreamEvent,
  SandboxGitFileEntry,
  SandboxThreadGitChangesResult,
  SandboxThreadGitCommitResult
} from '../../src/lib/sandbox.ts';

test('SandboxInitializeStepStatus type accepts valid values', () => {
  const statuses: SandboxInitializeStepStatus[] = [
    'pending',
    'running',
    'success',
    'error',
    'skipped'
  ];
  assert.equal(statuses.length, 5);
  assert.ok(statuses.includes('pending'));
  assert.ok(statuses.includes('running'));
  assert.ok(statuses.includes('success'));
  assert.ok(statuses.includes('error'));
  assert.ok(statuses.includes('skipped'));
});

test('SandboxInitializeStep structure is correct', () => {
  const step: SandboxInitializeStep = {
    key: 'clone-repo',
    title: 'Clone Repository',
    status: 'success',
    detail: 'Cloned repository successfully'
  };

  assert.equal(step.key, 'clone-repo');
  assert.equal(step.title, 'Clone Repository');
  assert.equal(step.status, 'success');
  assert.equal(step.detail, 'Cloned repository successfully');
});

test('SandboxInitializeStep without optional detail', () => {
  const step: SandboxInitializeStep = {
    key: 'setup-env',
    title: 'Setup Environment',
    status: 'pending'
  };

  assert.equal(step.key, 'setup-env');
  assert.equal(step.title, 'Setup Environment');
  assert.equal(step.status, 'pending');
  assert.equal(step.detail, undefined);
});

test('SandboxInitializeResult structure is correct', () => {
  const result: SandboxInitializeResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    status: 'ok',
    success: true,
    error: undefined,
    steps: [
      {
        key: 'step-1',
        title: 'Step 1',
        status: 'success'
      },
      {
        key: 'step-2',
        title: 'Step 2',
        status: 'success'
      }
    ],
    container_id: 'container-789',
    service_status: {
      'service-1': { running: true },
      'service-2': { running: false }
    },
    runtime_timestamp: '2024-03-15T10:30:00Z'
  };

  assert.equal(result.thread_id, 'thread-123');
  assert.equal(result.graph_id, 'graph-456');
  assert.equal(result.status, 'ok');
  assert.equal(result.success, true);
  assert.equal(result.steps.length, 2);
  assert.equal(result.container_id, 'container-789');
  assert.equal(result.service_status?.['service-1']?.running, true);
});

test('SandboxInitializeResult with error status', () => {
  const result: SandboxInitializeResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    status: 'error',
    success: false,
    error: 'Failed to initialize container',
    steps: [
      {
        key: 'step-1',
        title: 'Step 1',
        status: 'success'
      },
      {
        key: 'step-2',
        title: 'Step 2',
        status: 'error',
        detail: 'Container creation failed'
      }
    ]
  };

  assert.equal(result.status, 'error');
  assert.equal(result.success, false);
  assert.equal(result.error, 'Failed to initialize container');
  assert.equal(result.steps[1]?.status, 'error');
});

test('SandboxBootstrapStatus type accepts valid values', () => {
  const statuses: SandboxBootstrapStatus[] = [
    'idle',
    'running',
    'success',
    'error'
  ];
  assert.equal(statuses.length, 4);
  assert.ok(statuses.includes('idle'));
  assert.ok(statuses.includes('running'));
  assert.ok(statuses.includes('success'));
  assert.ok(statuses.includes('error'));
});

test('SandboxBootstrapLog structure is correct', () => {
  const log: SandboxBootstrapLog = {
    timestamp: '2024-03-15T10:30:00Z',
    level: 'info',
    step: 'setup',
    message: 'Setting up environment'
  };

  assert.equal(log.timestamp, '2024-03-15T10:30:00Z');
  assert.equal(log.level, 'info');
  assert.equal(log.step, 'setup');
  assert.equal(log.message, 'Setting up environment');
});

test('SandboxBootstrapLog with minimal fields', () => {
  const log: SandboxBootstrapLog = {
    message: 'Simple message'
  };

  assert.equal(log.message, 'Simple message');
  assert.equal(log.timestamp, undefined);
  assert.equal(log.level, undefined);
  assert.equal(log.step, undefined);
});

test('SandboxBootstrapResult structure is correct', () => {
  const result: SandboxBootstrapResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    status: 'success',
    accepted: true,
    request_id: 'req-789',
    run_id: 'run-abc',
    run_status: 'completed',
    error: null,
    steps: [
      { key: 'step1', title: 'Step 1', status: 'success' },
      { key: 'step2', title: 'Step 2', status: 'success' }
    ],
    logs: [
      { timestamp: '2024-01-01T00:00:00Z', message: 'Log 1' },
      { timestamp: '2024-01-01T00:00:01Z', message: 'Log 2' }
    ],
    event_seq: 42,
    started_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:01:00Z',
    finished_at: '2024-01-01T00:02:00Z',
    reset_success: true,
    reset_error: null,
    destroy_container: true,
    destroyed_container_id: 'container-abc'
  };

  assert.equal(result.thread_id, 'thread-123');
  assert.equal(result.graph_id, 'graph-456');
  assert.equal(result.status, 'success');
  assert.equal(result.accepted, true);
  assert.equal(result.request_id, 'req-789');
  assert.equal(result.run_id, 'run-abc');
  assert.equal(result.run_status, 'completed');
  assert.equal(result.error, null);
  assert.equal(result.steps.length, 2);
  assert.equal(result.logs.length, 2);
  assert.equal(result.event_seq, 42);
  assert.equal(result.started_at, '2024-01-01T00:00:00Z');
  assert.equal(result.updated_at, '2024-01-01T00:01:00Z');
  assert.equal(result.finished_at, '2024-01-01T00:02:00Z');
  assert.equal(result.reset_success, true);
  assert.equal(result.reset_error, null);
  assert.equal(result.destroy_container, true);
  assert.equal(result.destroyed_container_id, 'container-abc');
});

test('SandboxThreadCancelAction type accepts valid values', () => {
  const actions: SandboxThreadCancelAction[] = ['cancel', 'interrupt'];
  assert.equal(actions.length, 2);
  assert.ok(actions.includes('cancel'));
  assert.ok(actions.includes('interrupt'));
});

test('SandboxThreadCancelResult structure is correct', () => {
  const result: SandboxThreadCancelResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    action: 'cancel',
    cancelled_run_ids: ['run-1', 'run-2'],
    cancelled_run_count: 2,
    cancel_signal_failures: ['run-3'],
    bootstrap_task_cancelled: true,
    thread_status: 'idle',
    updated_at: '2024-03-15T10:30:00Z'
  };

  assert.equal(result.thread_id, 'thread-123');
  assert.equal(result.graph_id, 'graph-456');
  assert.equal(result.action, 'cancel');
  assert.equal(result.cancelled_run_ids.length, 2);
  assert.equal(result.cancelled_run_ids[0], 'run-1');
  assert.equal(result.cancelled_run_ids[1], 'run-2');
  assert.equal(result.cancelled_run_count, 2);
  assert.equal(result.cancel_signal_failures.length, 1);
  assert.equal(result.cancel_signal_failures[0], 'run-3');
  assert.equal(result.bootstrap_task_cancelled, true);
  assert.equal(result.thread_status, 'idle');
  assert.equal(result.updated_at, '2024-03-15T10:30:00Z');
});

test('SandboxBootstrapEvent structure is correct', () => {
  const event: SandboxBootstrapEvent = {
    seq: 1,
    type: 'log',
    timestamp: '2024-03-15T10:30:00Z',
    level: 'info',
    step: 'setup',
    message: 'Setting up environment'
  };

  assert.equal(event.seq, 1);
  assert.equal(event.type, 'log');
  assert.equal(event.timestamp, '2024-03-15T10:30:00Z');
  assert.equal(event.level, 'info');
  assert.equal(event.step, 'setup');
  assert.equal(event.message, 'Setting up environment');
});

test('SandboxBootstrapStreamEvent types are correct', () => {
  const eventEvent: SandboxBootstrapStreamEvent = {
    type: 'bootstrap_event',
    data: {
      seq: 1,
      type: 'log',
      message: 'Log message'
    }
  };

  const snapshotEvent: SandboxBootstrapStreamEvent = {
    type: 'bootstrap_snapshot',
    data: {
      thread_id: 'thread-123',
      graph_id: 'graph-456',
      status: 'running',
      steps: [],
      logs: []
    } as SandboxBootstrapResult
  };

  const doneEvent: SandboxBootstrapStreamEvent = {
    type: 'bootstrap_done',
    data: {
      thread_id: 'thread-123',
      status: 'success',
      event_seq: 42
    }
  };

  const errorEvent: SandboxBootstrapStreamEvent = {
    type: 'bootstrap_error',
    data: {
      thread_id: 'thread-123',
      error: 'Something went wrong',
      message: 'Error message'
    }
  };

  assert.equal(eventEvent.type, 'bootstrap_event');
  assert.equal(snapshotEvent.type, 'bootstrap_snapshot');
  assert.equal(doneEvent.type, 'bootstrap_done');
  assert.equal(errorEvent.type, 'bootstrap_error');
});

test('SandboxGitFileEntry structure is correct', () => {
  const entry: SandboxGitFileEntry = {
    status: 'M',
    index_status: 'M',
    worktree_status: 'M',
    path: 'src/index.ts',
    old_path: undefined,
    is_staged: true,
    is_unstaged: false
  };

  assert.equal(entry.status, 'M');
  assert.equal(entry.index_status, 'M');
  assert.equal(entry.worktree_status, 'M');
  assert.equal(entry.path, 'src/index.ts');
  assert.equal(entry.old_path, undefined);
  assert.equal(entry.is_staged, true);
  assert.equal(entry.is_unstaged, false);
});

test('SandboxGitFileEntry with renamed file', () => {
  const entry: SandboxGitFileEntry = {
    status: 'R',
    index_status: 'R',
    worktree_status: 'M',
    path: 'src/new-name.ts',
    old_path: 'src/old-name.ts',
    is_staged: true,
    is_unstaged: true
  };

  assert.equal(entry.status, 'R');
  assert.equal(entry.path, 'src/new-name.ts');
  assert.equal(entry.old_path, 'src/old-name.ts');
  assert.equal(entry.is_staged, true);
  assert.equal(entry.is_unstaged, true);
});

test('SandboxThreadGitChangesResult structure is correct', () => {
  const result: SandboxThreadGitChangesResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    files: [
      {
        status: 'M',
        index_status: 'M',
        worktree_status: 'M',
        path: 'src/index.ts',
        old_path: undefined,
        is_staged: true,
        is_unstaged: false
      },
      {
        status: 'A',
        index_status: 'A',
        worktree_status: 'A',
        path: 'src/new-file.ts',
        old_path: undefined,
        is_staged: true,
        is_unstaged: false
      }
    ],
    count: 2,
    untracked_files: ['untracked.txt'],
    diff: 'diff --git a/src/index.ts b/src/index.ts',
    diff_truncated: false,
    pending_initialization: false,
    timestamp: '2024-03-15T10:30:00Z'
  };

  assert.equal(result.thread_id, 'thread-123');
  assert.equal(result.graph_id, 'graph-456');
  assert.equal(result.files.length, 2);
  assert.equal(result.files[0]?.path, 'src/index.ts');
  assert.equal(result.files[1]?.path, 'src/new-file.ts');
  assert.equal(result.count, 2);
  assert.equal(result.untracked_files?.length, 1);
  assert.equal(result.untracked_files?.[0], 'untracked.txt');
  assert.equal(result.diff?.startsWith('diff --git'), true);
  assert.equal(result.diff_truncated, false);
  assert.equal(result.pending_initialization, false);
  assert.equal(result.timestamp, '2024-03-15T10:30:00Z');
});

test('SandboxThreadGitCommitResult structure is correct', () => {
  const result: SandboxThreadGitCommitResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    commit_id: 'abc123def456',
    commit_message: 'feat: add new feature',
    message_source: 'model',
    staged_count_before_commit: 3,
    staged_count_after_commit: 0,
    unstaged_count_after_commit: 1,
    commit_output: '[main abc123d] feat: add new feature',
    commit_output_truncated: false,
    timestamp: '2024-03-15T10:30:00Z'
  };

  assert.equal(result.thread_id, 'thread-123');
  assert.equal(result.graph_id, 'graph-456');
  assert.equal(result.commit_id, 'abc123def456');
  assert.equal(result.commit_message, 'feat: add new feature');
  assert.equal(result.message_source, 'model');
  assert.equal(result.staged_count_before_commit, 3);
  assert.equal(result.staged_count_after_commit, 0);
  assert.equal(result.unstaged_count_after_commit, 1);
  assert.equal(result.commit_output?.startsWith('[main'), true);
  assert.equal(result.commit_output_truncated, false);
  assert.equal(result.timestamp, '2024-03-15T10:30:00Z');
});

test('SandboxThreadGitCommitResult with user message source', () => {
  const result: SandboxThreadGitCommitResult = {
    thread_id: 'thread-123',
    graph_id: 'graph-456',
    commit_id: 'def789abc012',
    commit_message: 'fix: bug fix',
    message_source: 'user',
    staged_count_before_commit: 1,
    staged_count_after_commit: 0,
    unstaged_count_after_commit: 0
  };

  assert.equal(result.message_source, 'user');
  assert.equal(result.commit_message, 'fix: bug fix');
});
