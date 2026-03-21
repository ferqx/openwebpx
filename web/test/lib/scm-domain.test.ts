import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeGitlabBaseUrl,
  buildScmAuthorizationKey,
  resolveScmSourceLabel,
  parseScmConnectionSources,
  resolveScmApiOptionsFromSource,
  toSyntheticScmConnection,
  buildRepositoryOptionKey,
  isScmConnectionsEndpointUnavailable,
  getScmOAuthFailureMessage,
  readRememberedEnterpriseBaseUrls,
  rememberEnterpriseBaseUrls,
  readRememberedProviderHints,
  rememberProviderHints,
  SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY,
  SCM_PROVIDER_HINTS_STORAGE_KEY
} from '../../src/lib/scm-domain.ts';
import type { ScmConnection } from '../../src/lib/scm.ts';
import type { PortalScmSource } from '../../src/business/portal/types.ts';

// Simple mockStorage factory for each test
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

// Set up global window and localStorage before each test
test.beforeEach(() => {
  const mockStorage = createMockStorage();
  global.window = { localStorage: mockStorage } as unknown as Window & typeof globalThis;
  global.localStorage = mockStorage;
});

test('normalizeGitlabBaseUrl handles standard URLs', () => {
  assert.equal(normalizeGitlabBaseUrl('https://gitlab.company.com'), 'https://gitlab.company.com');
  assert.equal(normalizeGitlabBaseUrl('https://git.example.com:8080'), 'https://git.example.com:8080');
});

test('normalizeGitlabBaseUrl handles URLs with paths', () => {
  assert.equal(
    normalizeGitlabBaseUrl('https://gitlab.company.com/api/v4'),
    'https://gitlab.company.com'
  );
});

test('normalizeGitlabBaseUrl handles plain strings', () => {
  assert.equal(normalizeGitlabBaseUrl('gitlab.company.com'), 'gitlab.company.com');
  assert.equal(normalizeGitlabBaseUrl('GitLab.Example.COM'), 'gitlab.example.com');
});

test('normalizeGitlabBaseUrl handles empty input', () => {
  assert.equal(normalizeGitlabBaseUrl(''), '');
  assert.equal(normalizeGitlabBaseUrl('  '), '');
});

test('buildScmAuthorizationKey for github', () => {
  assert.equal(buildScmAuthorizationKey('github', ''), 'github');
  assert.equal(buildScmAuthorizationKey('github', 'https://gitlab.com'), 'github');
});

test('buildScmAuthorizationKey for gitlab', () => {
  assert.equal(buildScmAuthorizationKey('gitlab', ''), 'gitlab');
  assert.equal(buildScmAuthorizationKey('gitlab', 'https://gitlab.com'), 'gitlab');
});

test('buildScmAuthorizationKey for gitlab_enterprise', () => {
  assert.equal(
    buildScmAuthorizationKey('gitlab_enterprise', 'https://gitlab.company.com'),
    'gitlab_enterprise:https://gitlab.company.com'
  );
});

test('resolveScmSourceLabel for GitHub', () => {
  assert.equal(resolveScmSourceLabel({ provider: 'github' }), 'GitHub');
});

test('resolveScmSourceLabel for GitLab.com', () => {
  assert.equal(resolveScmSourceLabel({ provider: 'gitlab' }), 'GitLab.com');
});

test('resolveScmSourceLabel for GitLab Enterprise', () => {
  assert.equal(
    resolveScmSourceLabel({ provider: 'gitlab_enterprise' }),
    'GitLab 私有'
  );
  assert.equal(
    resolveScmSourceLabel({
      provider: 'gitlab_enterprise',
      gitlabBaseUrl: 'https://gitlab.company.com'
    }),
    'GitLab 私有 (gitlab.company.com)'
  );
});

test('parseScmConnectionSources handles empty array', () => {
  const sources = parseScmConnectionSources([]);
  assert.equal(sources.length, 0);
});

test('parseScmConnectionSources filters duplicates', () => {
  const connections: ScmConnection[] = [
    {
      provider: 'github',
      connectionKey: 'github',
      expired: false,
      hasRefreshToken: true
    },
    {
      provider: 'github',
      connectionKey: 'github',
      expired: false,
      hasRefreshToken: true
    }
  ];
  const sources = parseScmConnectionSources(connections);
  assert.equal(sources.length, 1);
  assert.equal(sources[0]?.provider, 'github');
});

test('parseScmConnectionSources sorts by provider order', () => {
  const connections: ScmConnection[] = [
    {
      provider: 'gitlab_enterprise',
      connectionKey: 'gitlab_enterprise:https://gitlab.company.com',
      gitlabBaseUrl: 'https://gitlab.company.com',
      expired: false,
      hasRefreshToken: true
    },
    {
      provider: 'gitlab',
      connectionKey: 'gitlab',
      expired: false,
      hasRefreshToken: true
    },
    {
      provider: 'github',
      connectionKey: 'github',
      expired: false,
      hasRefreshToken: true
    }
  ];
  const sources = parseScmConnectionSources(connections);
  assert.equal(sources[0]?.provider, 'github');
  assert.equal(sources[1]?.provider, 'gitlab');
  assert.equal(sources[2]?.provider, 'gitlab_enterprise');
});

test('resolveScmApiOptionsFromSource extracts API options', () => {
  const githubSource: PortalScmSource = {
    key: 'github',
    label: 'GitHub',
    provider: 'github'
  };
  const githubOptions = resolveScmApiOptionsFromSource(githubSource);
  assert.equal(githubOptions.provider, 'github');
  assert.equal(githubOptions.gitlabBaseUrl, undefined);

  const gitlabEnterpriseSource: PortalScmSource = {
    key: 'gitlab_enterprise:https://gitlab.company.com',
    label: 'GitLab 私有',
    provider: 'gitlab_enterprise',
    gitlabBaseUrl: 'https://gitlab.company.com'
  };
  const gitlabOptions = resolveScmApiOptionsFromSource(gitlabEnterpriseSource);
  assert.equal(gitlabOptions.provider, 'gitlab_enterprise');
  assert.equal(gitlabOptions.gitlabBaseUrl, 'https://gitlab.company.com');
});

test('toSyntheticScmConnection creates connection from source', () => {
  const githubSource: PortalScmSource = {
    key: 'github',
    label: 'GitHub',
    provider: 'github'
  };
  const githubConnection = toSyntheticScmConnection(githubSource);
  assert.equal(githubConnection.provider, 'github');
  assert.equal(githubConnection.connectionKey, 'github');
  assert.equal(githubConnection.githubAuthMode, 'github_app');
  assert.equal(githubConnection.expired, false);

  const gitlabSource: PortalScmSource = {
    key: 'gitlab',
    label: 'GitLab.com',
    provider: 'gitlab'
  };
  const gitlabConnection = toSyntheticScmConnection(gitlabSource);
  assert.equal(gitlabConnection.provider, 'gitlab');
  assert.equal(gitlabConnection.githubAuthMode, undefined);
});

test('buildRepositoryOptionKey builds option key', () => {
  assert.equal(
    buildRepositoryOptionKey('github', 'owner/repo'),
    'github::owner/repo'
  );
  assert.equal(
    buildRepositoryOptionKey('gitlab_enterprise:https://gitlab.company.com', 'group/project'),
    'gitlab_enterprise:https://gitlab.company.com::group/project'
  );
});

test('isScmConnectionsEndpointUnavailable detects unavailable errors', async () => {
  // Import the actual ScmRequestError class from scm module
  const { ScmRequestError } = await import('../../src/lib/scm.ts');

  // HTTP 400 error
  const error400 = new ScmRequestError('Bad Request', { status: 400 });
  assert.equal(isScmConnectionsEndpointUnavailable(error400), true);

  // HTTP 404 error
  const error404 = new ScmRequestError('Not Found', { status: 404 });
  assert.equal(isScmConnectionsEndpointUnavailable(error404), true);

  // HTTP 405 error
  const error405 = new ScmRequestError('Method Not Allowed', { status: 405 });
  assert.equal(isScmConnectionsEndpointUnavailable(error405), true);

  // HTTP 500 error should not be unavailable
  const error500 = new ScmRequestError('Internal Server Error', { status: 500 });
  assert.equal(isScmConnectionsEndpointUnavailable(error500), false);

  // Message contains auth_mode
  const authModeError = new ScmRequestError('Invalid auth_mode');
  assert.equal(isScmConnectionsEndpointUnavailable(authModeError), true);

  // Message contains provider
  const providerError = new ScmRequestError('Missing provider parameter');
  assert.equal(isScmConnectionsEndpointUnavailable(providerError), true);

  // Regular Error with HTTP 400 in message
  const regularError = new Error('HTTP 400 Bad Request');
  assert.equal(isScmConnectionsEndpointUnavailable(regularError), true);

  // Non-error value
  assert.equal(isScmConnectionsEndpointUnavailable(null), false);
  assert.equal(isScmConnectionsEndpointUnavailable('string'), false);
  assert.equal(isScmConnectionsEndpointUnavailable(123), false);
});

test('getScmOAuthFailureMessage returns appropriate messages', () => {
  // No error detail
  assert.equal(getScmOAuthFailureMessage('github'), 'OAuth 授权失败');
  assert.equal(getScmOAuthFailureMessage('gitlab'), 'OAuth 授权失败');

  // With detail
  assert.equal(
    getScmOAuthFailureMessage('github', 'Access denied'),
    'Access denied'
  );

  // GitHub OAuth timeout
  assert.equal(
    getScmOAuthFailureMessage('github', 'OAuth state 无效或已过期'),
    'GitHub App 授权已超时，请重新发起授权并尽量在 10 分钟内完成安装或确认。'
  );

  // Case insensitive check
  assert.equal(
    getScmOAuthFailureMessage('github', 'OAUTH STATE 无效或已过期'),
    'GitHub App 授权已超时，请重新发起授权并尽量在 10 分钟内完成安装或确认。'
  );
});

test('readRememberedEnterpriseBaseUrls reads from localStorage', () => {
  // Clear storage
  localStorage.clear();
  assert.deepEqual(readRememberedEnterpriseBaseUrls(), []);

  // Set valid data
  localStorage.setItem(
    SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY,
    JSON.stringify(['https://gitlab1.company.com', 'https://gitlab2.company.com'])
  );
  const urls = readRememberedEnterpriseBaseUrls();
  assert.equal(urls.length, 2);
  assert.equal(urls[0], 'https://gitlab1.company.com');
  assert.equal(urls[1], 'https://gitlab2.company.com');

  // Invalid JSON returns empty array
  localStorage.setItem(SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY, 'invalid json');
  assert.deepEqual(readRememberedEnterpriseBaseUrls(), []);

  // Non-array returns empty array
  localStorage.setItem(SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY, '{"key": "value"}');
  assert.deepEqual(readRememberedEnterpriseBaseUrls(), []);

  // Filters non-string items
  localStorage.setItem(
    SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY,
    JSON.stringify(['https://valid.com', 123, null, 'https://another.com'])
  );
  const filteredUrls = readRememberedEnterpriseBaseUrls();
  assert.equal(filteredUrls.length, 2);
  assert.equal(filteredUrls[0], 'https://valid.com');
  assert.equal(filteredUrls[1], 'https://another.com');
});

test('rememberEnterpriseBaseUrls writes to localStorage', () => {
  localStorage.clear();

  const sources: PortalScmSource[] = [
    { key: 'github', label: 'GitHub', provider: 'github' },
    { key: 'gitlab', label: 'GitLab', provider: 'gitlab' },
    {
      key: 'gitlab_enterprise:https://gitlab1.company.com',
      label: 'GitLab 私有 1',
      provider: 'gitlab_enterprise',
      gitlabBaseUrl: 'https://gitlab1.company.com'
    },
    {
      key: 'gitlab_enterprise:https://gitlab2.company.com',
      label: 'GitLab 私有 2',
      provider: 'gitlab_enterprise',
      gitlabBaseUrl: 'https://gitlab2.company.com'
    }
  ];

  rememberEnterpriseBaseUrls(sources);

  const stored = localStorage.getItem(SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY);
  assert.ok(stored);
  const parsed = JSON.parse(stored!) as string[];
  assert.equal(parsed.length, 2);
  assert.ok(parsed.includes('https://gitlab1.company.com'));
  assert.ok(parsed.includes('https://gitlab2.company.com'));

  // Removing all enterprise sources clears storage
  rememberEnterpriseBaseUrls([sources[0]!]);
  assert.equal(localStorage.getItem(SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY), null);
});

test('readRememberedProviderHints reads from localStorage', () => {
  localStorage.clear();
  assert.deepEqual(readRememberedProviderHints(), []);

  // Set valid data
  localStorage.setItem(
    SCM_PROVIDER_HINTS_STORAGE_KEY,
    JSON.stringify(['github', 'gitlab'])
  );
  const hints = readRememberedProviderHints();
  assert.equal(hints.length, 2);
  assert.equal(hints[0], 'github');
  assert.equal(hints[1], 'gitlab');

  // Invalid JSON returns empty array
  localStorage.setItem(SCM_PROVIDER_HINTS_STORAGE_KEY, 'invalid');
  assert.deepEqual(readRememberedProviderHints(), []);

  // Non-array returns empty array
  localStorage.setItem(SCM_PROVIDER_HINTS_STORAGE_KEY, '{"key": "value"}');
  assert.deepEqual(readRememberedProviderHints(), []);

  // Filters invalid providers
  localStorage.setItem(
    SCM_PROVIDER_HINTS_STORAGE_KEY,
    JSON.stringify(['github', 'invalid', 'gitlab_enterprise', 'gitlab', 123])
  );
  const filteredHints = readRememberedProviderHints();
  assert.equal(filteredHints.length, 3);
  assert.equal(filteredHints[0], 'github');
  assert.equal(filteredHints[1], 'gitlab_enterprise');
  assert.equal(filteredHints[2], 'gitlab');
});

test('rememberProviderHints merges and writes to localStorage', () => {
  localStorage.clear();

  const sources: PortalScmSource[] = [
    { key: 'github', label: 'GitHub', provider: 'github' },
    { key: 'gitlab', label: 'GitLab', provider: 'gitlab' }
  ];

  rememberProviderHints(sources);

  const stored = localStorage.getItem(SCM_PROVIDER_HINTS_STORAGE_KEY);
  assert.ok(stored);
  const parsed = JSON.parse(stored!) as string[];
  assert.equal(parsed.length, 2);
  assert.ok(parsed.includes('github'));
  assert.ok(parsed.includes('gitlab'));

  // Merges with existing
  const newSources: PortalScmSource[] = [
    { key: 'github', label: 'GitHub', provider: 'github' },
    { key: 'gitlab', label: 'GitLab', provider: 'gitlab' },
    {
      key: 'gitlab_enterprise:https://gitlab.company.com',
      label: 'GitLab 私有',
      provider: 'gitlab_enterprise',
      gitlabBaseUrl: 'https://gitlab.company.com'
    }
  ];
  rememberProviderHints(newSources);

  const mergedStored = localStorage.getItem(SCM_PROVIDER_HINTS_STORAGE_KEY);
  const mergedParsed = JSON.parse(mergedStored!) as string[];
  // gitlab_enterprise is filtered out
  assert.equal(mergedParsed.length, 2);
  assert.ok(mergedParsed.includes('github'));
  assert.ok(mergedParsed.includes('gitlab'));

  // Empty sources don't modify storage
  localStorage.setItem(
    SCM_PROVIDER_HINTS_STORAGE_KEY,
    JSON.stringify(['github'])
  );
  rememberProviderHints([]);
  const unchangedStored = localStorage.getItem(SCM_PROVIDER_HINTS_STORAGE_KEY);
  const unchangedParsed = JSON.parse(unchangedStored!) as string[];
  assert.equal(unchangedParsed.length, 1);
  assert.equal(unchangedParsed[0], 'github');
});
