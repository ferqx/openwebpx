import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('standalone code review settings page is reduced to a redirect shell', async () => {
  const source = await readFile(
    new URL('../../src/pages/code-review-settings.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /Navigate|navigate/);
  assert.doesNotMatch(source, /TableHeader/);
  assert.doesNotMatch(source, /updateCodeReviewRepositoryConfig/);
});
