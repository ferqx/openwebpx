import test from 'node:test';
import assert from 'node:assert/strict';
import { buildMessagesDigest } from '../../src/business/task-detail/task-detail-utils.ts';

// Tests for the logic behind message hydration in task detail
test('buildMessagesDigest generates different strings for different message lists', () => {
  const m1 = [
    { id: '1', type: 'human', content: 'hello' }
  ];
  const m2 = [
    { id: '1', type: 'human', content: 'hello world' }
  ];
  const m3 = [
    { id: '1', type: 'human', content: 'hello' },
    { id: '2', type: 'ai', content: 'hi' }
  ];

  const d1 = buildMessagesDigest(m1);
  const d2 = buildMessagesDigest(m2);
  const d3 = buildMessagesDigest(m3);

  assert.notEqual(d1, d2);
  assert.notEqual(d1, d3);
  assert.notEqual(d2, d3);
});

test('buildMessagesDigest is stable for same content', () => {
  const m1 = [
    { id: '1', type: 'human', content: 'hello' }
  ];
  const m2 = [
    { id: '1', type: 'human', content: 'hello' }
  ];

  assert.equal(buildMessagesDigest(m1), buildMessagesDigest(m2));
});
