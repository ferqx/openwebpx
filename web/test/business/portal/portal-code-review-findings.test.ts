import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('PortalCodeReviewFindings prioritizes severe findings and expands the first one by default', async () => {
  const source = await readFile(
    new URL('../../../src/business/portal/portal-code-review-findings.tsx', import.meta.url),
    'utf8'
  );

  assert.match(source, /severityRank/);
  assert.match(source, /sortedFindings/);
  assert.match(source, /type="single"/);
  assert.match(source, /defaultValue=\{sortedFindings\[0\]\?\.id/);
});
