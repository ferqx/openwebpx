import test from 'node:test';
import assert from 'node:assert/strict';

// Mock import.meta.env before importing scm.ts
// @ts-ignore
import.meta.env = {};

import {
  ScmRequestError,
  isScmUnauthorizedError,
  isValidScmBaseUrl,
  getScmOAuthSessionState,
  clearScmOAuthSessionState,
  persistScmOAuthResult,
  consumeScmOAuthResult,
  fetchScmRepositories,
  fetchScmConnections,
  fetchScmBranches,
  revokeScmConnection,
  validateScmConnection,
  startScmOAuthRedirect,
  completeScmOAuthCallback
} from '../../src/lib/scm.ts';

// Simple mockStorage factory
function createMockStorage() {
  const store = new Map<string, string>();
  return {
    getItem(key: string) { return store.get(key) ?? null; },
    setItem(key: string, value: string) { store.set(key, value); },
    removeItem(key: string) { store.delete(key); },
    clear() { store.clear(); },
    get length() { return store.size; },
    key(index: number) { const keys = Array.from(store.keys()); return keys[index] ?? null; }
  } as Storage;
}

test.beforeEach(() => {
  const mockStorage = createMockStorage();
  global.window = {
    localStorage: mockStorage,
    sessionStorage: mockStorage,
    location: {
      href: 'http://localhost',
      origin: 'http://localhost',
      assign: (url: string) => { global.window.location.href = url; }
    }
  } as unknown as Window & typeof globalThis;
  global.localStorage = mockStorage;
  global.sessionStorage = mockStorage;

  // Clean up process.env mocks
  delete process.env.VITE_SCM_REPOSITORIES_ENDPOINT;
  delete process.env.VITE_SCM_CONNECTIONS_ENDPOINT;

  // Mock fetch
  global.fetch = async () => {
    throw new Error('Fetch not mocked for this test');
  };
});

test('ScmRequestError stores status code', () => {
  const error = new ScmRequestError('Not Found', { status: 404 });
  assert.equal(error.message, 'Not Found');
  assert.equal(error.status, 404);
  assert.equal(error.name, 'ScmRequestError');
});

test('isScmUnauthorizedError detects 401 and 403 status', () => {
  assert.equal(isScmUnauthorizedError(new ScmRequestError('Err', { status: 401 })), true);
  assert.equal(isScmUnauthorizedError(new ScmRequestError('Err', { status: 403 })), true);
  assert.equal(isScmUnauthorizedError(new ScmRequestError('Err', { status: 404 })), false);
  assert.equal(isScmUnauthorizedError(new Error('unauthorized')), true);
  assert.equal(isScmUnauthorizedError(new Error('forbidden')), true);
  assert.equal(isScmUnauthorizedError(new Error('Other')), false);
});

test('isValidScmBaseUrl validates URL format', () => {
  assert.equal(isValidScmBaseUrl('https://github.com'), true);
  assert.equal(isValidScmBaseUrl('http://gitlab.local:8080'), true);
  assert.equal(isValidScmBaseUrl('not-a-url'), false);
  assert.equal(isValidScmBaseUrl(''), false);
});

test('OAuth session state management', () => {
  const state = {
    provider: 'github' as const,
    returnTo: '/home',
    gitlabBaseUrl: undefined
  };
  global.sessionStorage.setItem('openwebpx:scm-oauth-pending', JSON.stringify(state));

  assert.deepEqual(getScmOAuthSessionState(), state);

  clearScmOAuthSessionState();
  assert.equal(getScmOAuthSessionState(), null);
});

test('OAuth result management', () => {
  const result = {
    ok: true,
    provider: 'gitlab' as const,
    error: undefined,
    gitlabBaseUrl: undefined
  };
  persistScmOAuthResult(result);

  assert.deepEqual(consumeScmOAuthResult(), result);
  assert.equal(consumeScmOAuthResult(), null); // Consumed once
});

test('fetchScmRepositories returns repository list on success', async () => {
  const mockRepos = [{ id: '1', fullName: 'user/repo' }];
  global.fetch = async (url) => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ repositories: mockRepos })
    } as Response;
  };

  const repos = await fetchScmRepositories({ provider: 'github' });
  assert.deepEqual(repos, mockRepos);
});

test('fetchScmRepositories throws ScmRequestError with status on failure', async () => {
  let callCount = 0;
  global.fetch = async () => {
    callCount++;
    return {
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: async () => 'Internal Server Error Body'
    } as Response;
  };

  await assert.rejects(
    fetchScmRepositories({ provider: 'github' }),
    (err: ScmRequestError) => {
      assert.equal(err.status, 500);
      assert.match(err.message, /Internal Server Error Body/);
      return true;
    }
  );
  assert.ok(callCount > 0);
});

test('fetchScmConnections returns connection list', async () => {
  const mockConnections = [{ provider: 'github', connection_key: 'key1', expired: false, has_refresh_token: true }];
  global.fetch = async () => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ connections: mockConnections })
    } as Response;
  };

  const connections = await fetchScmConnections();
  assert.ok(Array.isArray(connections));
  assert.equal(connections[0].provider, 'github');
});

test('fetchScmBranches returns branch list', async () => {
  const mockBranches = ['main', 'develop'];
  global.fetch = async () => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ branches: mockBranches })
    } as Response;
  };

  const branches = await fetchScmBranches({ provider: 'github', repository: 'user/repo' });
  assert.deepEqual(branches, mockBranches);
});

test('revokeScmConnection calls delete endpoint', async () => {
  let method = '';
  global.fetch = async (url, init) => {
    method = init?.method ?? '';
    return { ok: true, status: 200, json: async () => ({ ok: true }) } as Response;
  };

  await revokeScmConnection({ provider: 'github', connectionKey: 'key1' });
  assert.equal(method, 'DELETE');
});

test('validateScmConnection calls validation endpoint', async () => {
  global.fetch = async () => {
    return { ok: true, status: 200, json: async () => ({ ok: true, valid: true }) } as Response;
  };

  const result = await validateScmConnection({ provider: 'github', connectionKey: 'key1' });
  // validateScmConnection returns an object with valid, revoked etc.
  assert.equal(result.valid, true);
});

test('startScmOAuthRedirect sets up session and redirects', async () => {
  global.fetch = async () => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ authorize_url: 'https://github.com/login/oauth' })
    } as Response;
  };

  await startScmOAuthRedirect({
    provider: 'github',
    redirectUri: 'http://localhost/callback',
    returnTo: '/success'
  });

  const session = getScmOAuthSessionState();
  assert.equal(session?.provider, 'github');
  assert.equal(session?.returnTo, '/success');
  assert.equal(global.window.location.href, 'https://github.com/login/oauth');
});

test('completeScmOAuthCallback consumes code and returns result', async () => {
  global.fetch = async () => {
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true })
    } as Response;
  };

  const query = new URLSearchParams('code=123');
  const result = await completeScmOAuthCallback(query);
  assert.equal(result.ok, true);
});

test('uses environment variable for endpoint if provided', async () => {
  const customEndpoint = 'https://api.custom.com/repos';
  process.env.VITE_SCM_REPOSITORIES_ENDPOINT = customEndpoint;

  let requestedUrl = '';
  global.fetch = async (url) => {
    requestedUrl = url.toString();
    return {
      ok: true,
      status: 200,
      json: async () => ({ repositories: [] })
    } as Response;
  };

  await fetchScmRepositories({ provider: 'github' });
  assert.ok(requestedUrl.startsWith(customEndpoint));
});
