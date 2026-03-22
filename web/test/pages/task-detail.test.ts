import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildBackToPortalState,
  deriveInitialAutoRunState,
  stripConsumedTaskRouteState
} from '../../src/pages/task-detail-route-state.ts';

test('deriveInitialAutoRunState only enables prompt when shouldAutoRun is true', () => {
  assert.deepEqual(
    deriveInitialAutoRunState({
      shouldAutoRun: true,
      initialPrompt: '  fix findings  ',
      portalTab: 'review'
    }),
    {
      shouldAutoRun: true,
      prompt: 'fix findings'
    }
  );

  assert.deepEqual(
    deriveInitialAutoRunState({
      shouldAutoRun: false,
      initialPrompt: 'ignored'
    }),
    {
      shouldAutoRun: false,
      prompt: ''
    }
  );
});

test('stripConsumedTaskRouteState removes one-shot auto-run fields but keeps portal context', () => {
  const nextState = stripConsumedTaskRouteState({
    shouldAutoRun: true,
    initialPrompt: 'fix findings',
    portalTab: 'review',
    task: {
      id: 'thread-1',
      title: 'Fix findings',
      repo: 'acme/web',
      branch: 'main',
      dateLabel: '3/22',
      updatedAt: '刚才',
      status: 'completed',
      prompt: 'fix findings'
    }
  });

  assert.deepEqual(nextState, {
    portalTab: 'review',
    task: {
      id: 'thread-1',
      title: 'Fix findings',
      repo: 'acme/web',
      branch: 'main',
      dateLabel: '3/22',
      updatedAt: '刚才',
      status: 'completed',
      prompt: 'fix findings'
    }
  });
});

test('buildBackToPortalState preserves review tab when returning to portal', () => {
  assert.deepEqual(buildBackToPortalState({ portalTab: 'review' }), {
    portalTab: 'review'
  });
  assert.equal(buildBackToPortalState(null), undefined);
});
