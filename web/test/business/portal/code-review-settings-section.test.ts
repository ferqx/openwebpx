import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('code review settings section includes repository search', async () => {
  const source = await readFile(
    new URL('../../../src/business/portal/code-review-settings-section.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /搜索仓库/);
  assert.match(source, /config_key: String\(repository\.id\)/);
  assert.doesNotMatch(source, /configs\[repo\.repository_identity_key\]/);
});
