import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('settings page exposes a code review section', async () => {
  const source = await readFile(
    new URL('../../src/pages/settings.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /代码审查/);
  assert.match(source, /code-review/);
  assert.doesNotMatch(source, /个人资料/);
  assert.match(source, /h-svh overflow-hidden bg-background/);
  assert.match(source, /TabsContent[\s\S]*overflow-auto/);
});
