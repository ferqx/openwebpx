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
  assert.match(source, /待审批修复/);
  assert.match(source, /已关联线程|未关联线程/);
  assert.doesNotMatch(source, /查看关联线程/);
  assert.doesNotMatch(source, /lg:grid-cols-\[minmax\(0,1fr\)_280px\]/);
});

test('stream provider only treats task detail route params as thread ids', async () => {
  const source = await readFile(
    new URL('../../src/provider/stream.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /matchPath\('\/tasks\/:id', location\.pathname\)/);
  assert.match(source, /const threadId = taskRouteMatch\?\.params\.id \?\? null/);
});
