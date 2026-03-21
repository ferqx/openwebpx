import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildEnvironmentDisplayFromBootstrap,
  buildEnvironmentResetDisplay
} from '../../src/hooks/thread-chat-utils.ts';
import { type SandboxBootstrapResult } from '../../src/lib/sandbox.ts';

test('buildEnvironmentDisplayFromBootstrap maps backend status to UI display model', () => {
  const mockSnapshot: SandboxBootstrapResult = {
    thread_id: 't1',
    graph_id: 'g1',
    status: 'running',
    request_id: 'req-123',
    steps: [
      { key: 'container', title: 'Container', status: 'success' },
      { key: 'repo', title: 'Repo', status: 'running' }
    ],
    logs: [{ message: 'cloning...', level: 'info' }],
    event_seq: 10
  };

  const display = buildEnvironmentDisplayFromBootstrap(mockSnapshot);

  assert.equal(display.id, 'req-123'); // matches request_id
  assert.equal(display.status, 'running');
  assert.equal(display.steps.length, 2);
  assert.equal(display.logs[0].message, 'cloning...');
});

test('buildEnvironmentResetDisplay maps reset result to UI display model', () => {
  const resetResult = {
    thread_id: 't1',
    reset_success: true,
    steps: [],
    logs: [{ message: 'cleaning up', level: 'info' }]
  };

  const display = buildEnvironmentResetDisplay(resetResult);

  assert.match(display.id, /^bootstrap-reset-/); // id is generated with Date.now()
  assert.equal(display.status, 'success');
  assert.equal(display.logs.length, 1);
});

test('isEnvironmentInitializing logic verification', () => {
  // Logic from useThreadEnvironmentBootstrap
  const check = (enable: boolean, threadId: string, isReady: boolean, status?: string) => {
    return enable && threadId.length > 0 && !isReady && status === 'running';
  };

  assert.equal(check(true, 't1', false, 'running'), true);
  assert.equal(check(true, '', false, 'running'), false); // no thread id
  assert.equal(check(true, 't1', true, 'running'), false); // already ready
  assert.equal(check(false, 't1', false, 'running'), false); // disabled
  assert.equal(check(true, 't1', false, 'success'), false); // not running
});
