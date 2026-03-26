import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

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

test('portal page constrains main content area to half width', async () => {
  const source = await readFile(
    new URL('../../src/pages/portal.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /className="mx-auto w-1\/2 space-y-4"/);
  assert.match(
    source,
    /<div className="sticky[\s\S]*?<PortalPromptPanel[\s\S]*?<PortalTaskToolbar[\s\S]*?<\/div>/
  );
});

test('portal review selection navigates to dedicated review detail route', async () => {
  const source = await readFile(
    new URL('../../src/hooks/use-portal-page-controller.ts', import.meta.url),
    'utf8'
  );

  assert.match(source, /navigate\(`\/reviews\/\$\{runId\}`/);
  assert.doesNotMatch(source, /navigate\(`\/tasks\/\$\{targetId\}`/);
});
