import test from 'node:test';
import assert from 'node:assert/strict';
import type { Thread, ThreadStatus } from '@langchain/langgraph-sdk';
import {
  mapThreadToTaskItem,
  mapThreadsToTaskItems,
  statusLabel,
  type TaskStatus
} from '../../src/lib/tasks.ts';

test('statusLabel contains all task statuses', () => {
  assert.equal(statusLabel.completed, 'Completed');
  assert.equal(statusLabel.running, 'Running');
  assert.equal(statusLabel.starting, 'Starting container');
  assert.equal(statusLabel.stopped, 'Stopped');
});

test('mapThreadToTaskItem maps basic thread correctly', () => {
  const thread: Thread = {
    thread_id: 'thread-123',
    status: 'idle',
    created_at: '2024-01-15T08:30:00Z',
    updated_at: '2024-01-15T09:45:00Z',
    metadata: {
      name: 'Test Task',
      prompt: 'Implement feature X',
      repo: 'owner/repo',
      branch: 'feature-branch'
    }
  };

  const task = mapThreadToTaskItem(thread);

  assert.equal(task.id, 'thread-123');
  assert.equal(task.title, 'Test Task');
  assert.equal(task.prompt, 'Implement feature X');
  assert.equal(task.repo, 'owner/repo');
  assert.equal(task.branch, 'feature-branch');
  assert.equal(task.status, 'completed');
  assert.equal(task.createdAt, '2024-01-15T08:30:00Z');
});

test('mapThreadToTaskItem uses thread_id as fallback for title', () => {
  const thread: Thread = {
    thread_id: 'abc-def-123',
    status: 'idle',
    created_at: '2024-01-15T08:30:00Z',
    updated_at: '2024-01-15T09:45:00Z',
    metadata: {}
  };

  const task = mapThreadToTaskItem(thread);

  assert.equal(task.title, '线程 abc-def-');
  assert.equal(task.prompt, '线程 abc-def-');
});

test('mapThreadToTaskItem uses default values for missing metadata', () => {
  const thread: Thread = {
    thread_id: 'thread-456',
    status: 'idle',
    created_at: '2024-01-15T08:30:00Z',
    updated_at: '2024-01-15T09:45:00Z',
    metadata: {}
  };

  const task = mapThreadToTaskItem(thread);

  assert.equal(task.repo, '未绑定仓库');
  assert.equal(task.branch, 'main');
});

test('mapThreadToTaskItem maps thread status correctly', () => {
  const baseThread: Omit<Thread, 'status'> = {
    thread_id: 'thread-789',
    created_at: '2024-01-15T08:30:00Z',
    updated_at: '2024-01-15T09:45:00Z',
    metadata: {}
  };

  const testCases: { input: ThreadStatus; expected: TaskStatus }[] = [
    { input: 'busy', expected: 'running' },
    { input: 'idle', expected: 'completed' },
    { input: 'error', expected: 'stopped' },
    { input: 'interrupted', expected: 'stopped' }
  ];

  for (const { input, expected } of testCases) {
    const thread: Thread = { ...baseThread, status: input };
    const task = mapThreadToTaskItem(thread);
    assert.equal(task.status, expected, `Expected status ${expected} for thread status ${input}`);
  }
});

test('mapThreadToTaskItem formats date labels correctly', () => {
  const thread: Thread = {
    thread_id: 'thread-date',
    status: 'idle',
    created_at: '2024-03-15T08:30:00Z',
    updated_at: '2024-03-15T10:45:00Z',
    metadata: {}
  };

  const task = mapThreadToTaskItem(thread);

  // Date label should be in Chinese format (3月15日)
  assert.ok(task.dateLabel.includes('3') || task.dateLabel.includes('三'));
});

test('mapThreadToTaskItem formats relative updated time correctly', () => {
  const now = new Date();
  const tenMinutesAgo = new Date(now.getTime() - 10 * 60 * 1000);
  const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
  const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);

  const testCases = [
    { date: tenMinutesAgo, expected: '10 分钟前' },
    { date: oneHourAgo, expected: '1 小时前' },
    { date: oneDayAgo, expected: '1 天前' }
  ];

  for (const { date, expected } of testCases) {
    const thread: Thread = {
      thread_id: 'thread-time',
      status: 'idle',
      created_at: new Date().toISOString(),
      updated_at: date.toISOString(),
      metadata: {}
    };

    const task = mapThreadToTaskItem(thread);
    assert.equal(task.updatedAt, expected);
  }
});

test('mapThreadToTaskItem returns 刚才 for very recent updates', () => {
  const thirtySecondsAgo = new Date(Date.now() - 30 * 1000);

  const thread: Thread = {
    thread_id: 'thread-just-now',
    status: 'idle',
    created_at: new Date().toISOString(),
    updated_at: thirtySecondsAgo.toISOString(),
    metadata: {}
  };

  const task = mapThreadToTaskItem(thread);
  assert.equal(task.updatedAt, '刚才');
});

test('mapThreadsToTaskItems sorts by created date descending', () => {
  const threads: Thread[] = [
    {
      thread_id: 'thread-1',
      status: 'idle',
      created_at: '2024-01-15T10:00:00Z',
      updated_at: '2024-01-15T10:00:00Z',
      metadata: { name: 'Task 1' }
    },
    {
      thread_id: 'thread-2',
      status: 'idle',
      created_at: '2024-01-15T12:00:00Z',
      updated_at: '2024-01-15T12:00:00Z',
      metadata: { name: 'Task 2' }
    },
    {
      thread_id: 'thread-3',
      status: 'idle',
      created_at: '2024-01-15T08:00:00Z',
      updated_at: '2024-01-15T08:00:00Z',
      metadata: { name: 'Task 3' }
    }
  ];

  const tasks = mapThreadsToTaskItems(threads);

  // Should be sorted by created date descending (newest first)
  assert.equal(tasks[0]?.id, 'thread-2'); // 12:00
  assert.equal(tasks[1]?.id, 'thread-1'); // 10:00
  assert.equal(tasks[2]?.id, 'thread-3'); // 08:00
});

test('mapThreadsToTaskItems handles empty array', () => {
  const tasks = mapThreadsToTaskItems([]);
  assert.equal(tasks.length, 0);
});

test('mapThreadsToTaskItems handles missing createdAt', () => {
  const threads: Thread[] = [
    {
      thread_id: 'thread-1',
      status: 'idle',
      created_at: '2024-01-15T10:00:00Z',
      updated_at: '2024-01-15T10:00:00Z',
      metadata: {}
    },
    {
      thread_id: 'thread-2',
      status: 'idle',
      // No created_at
      created_at: '',
      updated_at: '2024-01-15T12:00:00Z',
      metadata: {}
    }
  ];

  const tasks = mapThreadsToTaskItems(threads);

  // Thread without created_at should be at the end (treated as 0)
  assert.equal(tasks[0]?.id, 'thread-1');
  assert.equal(tasks[1]?.id, 'thread-2');
});

test('mapThreadToTaskItem handles metadata with non-string values', () => {
  const thread: Thread = {
    thread_id: 'thread-meta',
    status: 'idle',
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:00:00Z',
    metadata: {
      name: 123, // Number instead of string
      repo: null,
      branch: undefined,
      prompt: true
    }
  };

  const task = mapThreadToTaskItem(thread);

  // Should use fallbacks for non-string metadata values
  assert.equal(task.title, '线程 thread-m'); // Fallback to thread_id
  assert.equal(task.repo, '未绑定仓库'); // Fallback
  assert.equal(task.branch, 'main'); // Fallback
  assert.equal(task.prompt, '线程 thread-m'); // Fallback to title
});

test('mapThreadToTaskItem handles whitespace-only metadata values', () => {
  const thread: Thread = {
    thread_id: 'thread-ws',
    status: 'idle',
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:00:00Z',
    metadata: {
      name: '   ',
      repo: '\t\n',
      branch: '  main  '
    }
  };

  const task = mapThreadToTaskItem(thread);

  // Whitespace-only values should be treated as empty
  assert.equal(task.title, '线程 thread-w'); // Fallback
  assert.equal(task.repo, '未绑定仓库'); // Fallback
  assert.equal(task.branch, 'main'); // Trimmed value
});
