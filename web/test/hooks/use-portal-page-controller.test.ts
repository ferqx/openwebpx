import test from 'node:test';
import assert from 'node:assert/strict';

test('portal tab helpers accept review while preserving tasks fallback', async () => {
  const { portalTabs, isPortalTab, resolvePortalRouteTab } = await import(
    '../../src/business/portal/types.ts'
  );
  assert.deepEqual(portalTabs, ['tasks', 'review']);
  assert.equal(isPortalTab('tasks'), true);
  assert.equal(isPortalTab('review'), true);
  assert.equal(isPortalTab('unknown'), false);
  assert.equal(resolvePortalRouteTab('review'), 'review');
  assert.equal(resolvePortalRouteTab('tasks'), 'tasks');
  assert.equal(resolvePortalRouteTab('invalid'), undefined);
});

test('portal toolbar action switches between search and settings', async () => {
  const { resolvePortalToolbarAction } = await import(
    '../../src/business/portal/portal-task-toolbar.tsx'
  );
  const tasksAction = resolvePortalToolbarAction('tasks');
  const reviewAction = resolvePortalToolbarAction('review');

  const _tasksActionCheck: 'search' | 'settings' = tasksAction;
  const _reviewActionCheck: 'search' | 'settings' = reviewAction;
  void _tasksActionCheck;
  void _reviewActionCheck;
  assert.equal(tasksAction, 'search');
  assert.equal(reviewAction, 'settings');
});
