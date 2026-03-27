import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('app registers dedicated review detail route', async () => {
  const source = await readFile(
    new URL('../../src/App.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /path="reviews\/:id"/);
});

test('review detail page provides standalone review-page framing', async () => {
  const source = await readFile(
    new URL('../../src/pages/review-detail.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /返回代码审查/);
  assert.match(source, /max-w-5xl/);
  assert.match(source, /当前审查/);
  assert.match(source, /待审批修复/);
  assert.match(source, /已关联线程|未关联线程/);
  assert.match(source, /sticky top-0 z-10 border-b bg-background\/95 backdrop-blur/);
  assert.match(source, /Separator orientation="vertical"/);
  assert.match(source, /Review #/);
  assert.match(source, /MR\/PR #/);
  assert.match(source, /flex w-full flex-col gap-2 px-4 py-3/);
  assert.doesNotMatch(source, /查看关联线程/);
  assert.doesNotMatch(source, /代码审查详情/);
  assert.doesNotMatch(source, /先看审查结果，再决定是否修复/);
  assert.doesNotMatch(source, /<Card/);
  assert.doesNotMatch(source, /lg:grid-cols-\[minmax\(0,1fr\)_280px\]/);
  assert.doesNotMatch(source, /PortalHeader/);
});

test('stream provider only treats task detail route params as thread ids', async () => {
  const source = await readFile(
    new URL('../../src/provider/stream.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /matchPath\('\/tasks\/:id', location\.pathname\)/);
  assert.match(source, /const threadId = taskRouteMatch\?\.params\.id \?\? null/);
});
