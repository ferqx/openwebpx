import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getStoredAuthToken,
  setStoredAuthToken,
  clearStoredAuthToken,
  withAuthHeaders
} from '../../src/lib/auth.ts';

// Mock localStorage
const mockStorage = new Map<string, string>();
const AUTH_TOKEN_KEY = 'openwebpx:auth-token';

test.beforeEach(() => {
  mockStorage.clear();
});

// Mock global window object
global.window = {
  localStorage: {
    getItem: (key: string) => mockStorage.get(key) ?? null,
    setItem: (key: string, value: string) => mockStorage.set(key, value),
    removeItem: (key: string) => mockStorage.delete(key)
  }
} as typeof window;

test('getStoredAuthToken returns empty string when no token', () => {
  const token = getStoredAuthToken();
  assert.equal(token, '');
});

test('getStoredAuthToken returns stored token', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'test-token-123');
  const token = getStoredAuthToken();
  assert.equal(token, 'test-token-123');
});

test('setStoredAuthToken stores token', () => {
  setStoredAuthToken('new-token-456');
  assert.equal(mockStorage.get(AUTH_TOKEN_KEY), 'new-token-456');
});

test('setStoredAuthToken trims whitespace', () => {
  setStoredAuthToken('  token-with-spaces  ');
  assert.equal(mockStorage.get(AUTH_TOKEN_KEY), 'token-with-spaces');
});

test('setStoredAuthToken removes token when empty string', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'existing-token');
  setStoredAuthToken('');
  assert.equal(mockStorage.has(AUTH_TOKEN_KEY), false);
});

test('setStoredAuthToken removes token when only whitespace', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'existing-token');
  setStoredAuthToken('   ');
  assert.equal(mockStorage.has(AUTH_TOKEN_KEY), false);
});

test('clearStoredAuthToken removes token', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'token-to-clear');
  clearStoredAuthToken();
  assert.equal(mockStorage.has(AUTH_TOKEN_KEY), false);
});

test('clearStoredAuthToken does nothing when no token', () => {
  assert.doesNotThrow(() => {
    clearStoredAuthToken();
  });
});

test('withAuthHeaders adds Authorization header when token exists', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'bearer-token');
  const init = withAuthHeaders({ method: 'GET' });
  const headers = init.headers as Headers;
  assert.equal(headers.get('Authorization'), 'Bearer bearer-token');
});

test('withAuthHeaders does not override existing Authorization header', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'bearer-token');
  const init = withAuthHeaders({
    method: 'GET',
    headers: { Authorization: 'Bearer existing-token' }
  });
  const headers = init.headers as Headers;
  assert.equal(headers.get('Authorization'), 'Bearer existing-token');
});

test('withAuthHeaders does not add Authorization when no token', () => {
  const init = withAuthHeaders({ method: 'GET' });
  const headers = init.headers as Headers;
  assert.equal(headers.get('Authorization'), null);
});

test('withAuthHeaders preserves other headers', () => {
  mockStorage.set(AUTH_TOKEN_KEY, 'token');
  const init = withAuthHeaders({
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Custom-Header': 'custom-value'
    }
  });
  const headers = init.headers as Headers;
  assert.equal(headers.get('Content-Type'), 'application/json');
  assert.equal(headers.get('X-Custom-Header'), 'custom-value');
  assert.equal(headers.get('Authorization'), 'Bearer token');
});
