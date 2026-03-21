import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseScmConnectionSources,
  toSyntheticScmConnection,
  buildScmAuthorizationKey
} from '../../src/lib/scm-domain.ts';
import { type ScmConnection } from '../../src/lib/scm.ts';

// Since the project currently lacks a full React Hook testing environment (like react-testing-library),
// we will focus on testing the core logic and data transformations that drive usePortalScmConnections.

test('parseScmConnectionSources transforms connections to portal sources', () => {
  const connections: ScmConnection[] = [
    {
      provider: 'github',
      connectionKey: 'github-123',
      expired: false,
      hasRefreshToken: true,
      githubAuthMode: 'github_app'
    },
    {
      provider: 'gitlab_enterprise',
      connectionKey: 'gitlab-456',
      expired: true,
      hasRefreshToken: false,
      gitlabBaseUrl: 'https://gitlab.company.com'
    }
  ];

  const sources = parseScmConnectionSources(connections);

  assert.equal(sources.length, 2);
  assert.equal(sources[0].provider, 'github');
  assert.equal(sources[0].key, 'github-123'); // actual implementation uses connectionKey

  assert.equal(sources[1].provider, 'gitlab_enterprise');
  assert.equal(sources[1].gitlabBaseUrl, 'https://gitlab.company.com');
});

test('toSyntheticScmConnection creates a mock connection from a source', () => {
  const source = {
    key: 'custom-gitlab',
    label: 'Company GitLab',
    provider: 'gitlab_enterprise' as const,
    gitlabBaseUrl: 'https://gitlab.my.com'
  };

  const connection = toSyntheticScmConnection(source);

  assert.equal(connection.provider, 'gitlab_enterprise');
  assert.equal(connection.gitlabBaseUrl, 'https://gitlab.my.com');
  assert.equal(connection.connectionKey, 'custom-gitlab');
  assert.equal(connection.expired, false);
});

test('buildScmAuthorizationKey generates consistent keys', () => {
  const k1 = buildScmAuthorizationKey('github', undefined);
  const k2 = buildScmAuthorizationKey('gitlab_enterprise', 'https://git.com');
  const k3 = buildScmAuthorizationKey('gitlab_enterprise', 'https://git.com/'); // trailing slash

  assert.equal(k1, 'github');
  assert.equal(k2, 'gitlab_enterprise:https://git.com'); // single colon in actual implementation
  assert.equal(k3, 'gitlab_enterprise:https://git.com');
});
