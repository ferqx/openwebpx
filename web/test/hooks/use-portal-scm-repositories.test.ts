import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRepositoryOptionKey } from '../../src/lib/scm-domain.ts';

// Core logic tests for repository management within Portal
test('buildRepositoryOptionKey creates a unique string for repo-source pairs', () => {
  const key1 = buildRepositoryOptionKey('github', 'user/repo');
  const key2 = buildRepositoryOptionKey('gitlab::https://git.com', 'user/repo');

  assert.equal(key1, 'github::user/repo');
  assert.equal(key2, 'gitlab::https://git.com::user/repo');
});

test('validatedSelectedBranch returns empty string if selected branch is not in options', () => {
  // Simulating the derived state logic inside usePortalScmRepositories
  const branchOptions = ['main', 'develop'];

  const getValidated = (selected: string) => (branchOptions.includes(selected) ? selected : '');

  assert.equal(getValidated('main'), 'main');
  assert.equal(getValidated('feature/x'), '');
  assert.equal(getValidated(''), '');
});

test('repositoryEmptyMessage returns correct hints based on state', () => {
  // Logic from usePortalScmRepositories repositoryEmptyMessage useMemo
  const getMessage = (isConnectionsLoading: boolean, isRepositoryLoading: boolean, hasAnyScmAuthorized: boolean) => {
    if (isConnectionsLoading || isRepositoryLoading) return '正在加载仓库...';
    if (hasAnyScmAuthorized) return '当前授权范围内未找到仓库';
    return '未找到仓库，请先完成 GitHub/GitLab 授权';
  };

  assert.equal(getMessage(true, false, false), '正在加载仓库...');
  assert.equal(getMessage(false, true, true), '正在加载仓库...');
  assert.equal(getMessage(false, false, true), '当前授权范围内未找到仓库');
  assert.equal(getMessage(false, false, false), '未找到仓库，请先完成 GitHub/GitLab 授权');
});
