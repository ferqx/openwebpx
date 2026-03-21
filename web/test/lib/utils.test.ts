import test from 'node:test';
import assert from 'node:assert/strict';
import { cn } from '../../src/lib/utils.ts';

test('cn merges basic tailwind classes', () => {
  const result = cn('px-4 py-2', 'text-red-500');
  assert.equal(result, 'px-4 py-2 text-red-500');
});

test('cn handles conditional classes', () => {
  const isActive = true;
  const isDisabled = false;
  const result = cn(
    'base-class',
    isActive && 'active-class',
    isDisabled && 'disabled-class'
  );
  assert.equal(result, 'base-class active-class');
});

test('cn handles undefined and null values', () => {
  const result = cn('base', undefined, null, 'end');
  assert.equal(result, 'base end');
});

test('cn handles empty strings', () => {
  const result = cn('', 'class', '', 'end', '');
  assert.equal(result, 'class end');
});

test('cn handles array of classes', () => {
  const result = cn(['class1', 'class2'], 'class3');
  assert.equal(result, 'class1 class2 class3');
});

test('cn handles object syntax for conditional classes', () => {
  const result = cn({
    'active-class': true,
    'inactive-class': false,
    'always-class': true
  });
  assert.equal(result, 'active-class always-class');
});

test('cn resolves tailwind class conflicts (later wins)', () => {
  const result = cn('px-4', 'px-8');
  assert.equal(result, 'px-8');
});

test('cn resolves color conflicts correctly', () => {
  const result = cn('text-red-500', 'text-blue-600');
  assert.equal(result, 'text-blue-600');
});

test('cn handles mixed input types', () => {
  const result = cn(
    'base',
    ['array1', 'array2'],
    { conditional: true },
    undefined,
    'final'
  );
  assert.equal(result, 'base array1 array2 conditional final');
});

test('cn returns empty string for no arguments', () => {
  const result = cn();
  assert.equal(result, '');
});

test('cn returns empty string for only falsy values', () => {
  const result = cn(null, undefined, false, '');
  assert.equal(result, '');
});
