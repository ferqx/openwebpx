import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  consumeScmOAuthResult,
  isValidScmBaseUrl,
  startScmOAuthRedirect,
  type ScmProvider
} from '@/lib/scm';
import {
  buildScmAuthorizationKey,
  getScmOAuthFailureMessage,
  normalizeGitlabBaseUrl,
  rememberEnterpriseBaseUrls,
  rememberProviderHints,
  resolveScmSourceLabel
} from '@/lib/scm-domain';
import { usePortalScmConnections } from '@/hooks/use-portal-scm-connections';
import { usePortalScmRepositories } from '@/hooks/use-portal-scm-repositories';
import { type PortalScmSource } from '@/business/portal/types';

const models = ['2x', '4x', '8x'];
const envRepoSearchId = 'env-repo-search';

type UsePortalScmStateOptions = {
  pathname: string;
  search: string;
  hash: string;
};

export const usePortalScmState = ({
  pathname,
  search,
  hash
}: UsePortalScmStateOptions) => {
  const [isAuthorizingScm, setIsAuthorizingScm] = useState(false);
  const [authDialogProvider, setAuthDialogProvider] =
    useState<ScmProvider>('github');
  const [authDialogGitlabBaseUrl, setAuthDialogGitlabBaseUrl] = useState('');
  const [scmOauthDialogOpen, setScmOauthDialogOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState(models[0]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [selectedOrg, setSelectedOrg] = useState('');
  const [envRepoQuery, setEnvRepoQuery] = useState('');
  const [selectedEnvRepo, setSelectedEnvRepo] = useState<string>('');
  const [networkAccess, setNetworkAccess] = useState<'off' | 'on'>('off');

  const [filterSourcesState, setFilterSourcesState] = useState<
    PortalScmSource[]
  >([]);

  const connectionsState = usePortalScmConnections({
    onFilterInvalidRepositoryOptions: setFilterSourcesState
  });
  const repositoriesState = usePortalScmRepositories({
    authorizedScmSources: connectionsState.authorizedScmSources,
    isScmConnectionsLoading: connectionsState.isScmConnectionsLoading,
    isScmConnectionsApiUnavailable: connectionsState.isScmConnectionsApiUnavailable,
    onSyncInvalidSources: connectionsState.syncInvalidScmSources
  });

  useEffect(() => {
    if (filterSourcesState.length === 0) return;
    repositoriesState.filterRepositoryOptionsBySources(filterSourcesState);
    setFilterSourcesState([]);
  }, [filterSourcesState, repositoriesState]);

  const orgs = useMemo(
    () =>
      Array.from(
        new Set(
          repositoriesState.repositoryNames
            .map((repo) => repo.split('/')[0]?.trim())
            .filter((org): org is string => Boolean(org))
        )
      ),
    [repositoriesState.repositoryNames]
  );
  const filteredEnvRepos = useMemo(() => {
    const source = selectedOrg
      ? repositoriesState.repositoryNames.filter((repo) =>
          repo.startsWith(`${selectedOrg}/`)
        )
      : repositoriesState.repositoryNames;
    const query = envRepoQuery.trim().toLowerCase();
    if (!query) return source;
    return source.filter((repo) => repo.toLowerCase().includes(query));
  }, [envRepoQuery, repositoriesState.repositoryNames, selectedOrg]);

  useEffect(() => {
    if (selectedOrg && orgs.includes(selectedOrg)) return;
    setSelectedOrg(orgs[0] ?? '');
  }, [orgs, selectedOrg]);

  useEffect(() => {
    if (!selectedEnvRepo) return;
    if (filteredEnvRepos.includes(selectedEnvRepo)) return;
    setSelectedEnvRepo('');
  }, [filteredEnvRepos, selectedEnvRepo]);

  const handleAuthorizeScm = useCallback(async () => {
    if (isAuthorizingScm) return;
    if (
      authDialogProvider === 'gitlab_enterprise' &&
      !isValidScmBaseUrl(authDialogGitlabBaseUrl)
    ) {
      toast.error('请输入合法的 GitLab 企业地址');
      return;
    }
    setIsAuthorizingScm(true);
    try {
      await startScmOAuthRedirect({
        provider: authDialogProvider,
        redirectUri: `${window.location.origin}/oauth/scm/callback`,
        returnTo: `${pathname}${search}${hash}`,
        gitlabBaseUrl:
          authDialogProvider === 'gitlab_enterprise'
            ? authDialogGitlabBaseUrl
            : undefined
      });
    } catch (error) {
      console.error('Failed to authorize scm provider', error);
      setIsAuthorizingScm(false);
      toast.error(
        error instanceof Error && error.message.trim()
          ? error.message
          : 'OAuth 授权失败'
      );
    }
  }, [
    authDialogGitlabBaseUrl,
    authDialogProvider,
    hash,
    isAuthorizingScm,
    pathname,
    search
  ]);

  useEffect(() => {
    const oauthResult = consumeScmOAuthResult();
    if (!oauthResult) return;

    let cancelled = false;
    const run = async () => {
      if (!oauthResult.ok) {
        toast.error(
          getScmOAuthFailureMessage(oauthResult.provider, oauthResult.error)
        );
        return;
      }

      const enterpriseBaseUrl = oauthResult.gitlabBaseUrl;
      if (
        oauthResult.provider === 'gitlab_enterprise' &&
        enterpriseBaseUrl &&
        isValidScmBaseUrl(enterpriseBaseUrl)
      ) {
        const normalizedBaseUrl = normalizeGitlabBaseUrl(enterpriseBaseUrl);
        rememberEnterpriseBaseUrls([
          ...connectionsState.authorizedScmSources,
          {
            key: buildScmAuthorizationKey('gitlab_enterprise', normalizedBaseUrl),
            label: resolveScmSourceLabel({
              provider: 'gitlab_enterprise',
              gitlabBaseUrl: normalizedBaseUrl
            }),
            provider: 'gitlab_enterprise',
            gitlabBaseUrl: normalizedBaseUrl
          }
        ]);
      }
      if (
        oauthResult.provider === 'github' ||
        oauthResult.provider === 'gitlab'
      ) {
        rememberProviderHints([
          {
            key: oauthResult.provider,
            label: resolveScmSourceLabel({ provider: oauthResult.provider }),
            provider: oauthResult.provider
          }
        ]);
      }

      try {
        const latestSources = await connectionsState.loadScmConnections({ silent: true });
        if (cancelled) return;
        toast.success('授权成功，正在刷新仓库列表');
        setScmOauthDialogOpen(false);
        await repositoriesState.loadRepositories({
          force: true,
          sources: latestSources
        });
      } catch (error) {
        if (cancelled) return;
        console.error('Failed to refresh repositories after scm oauth', error);
        toast.error('授权成功，但刷新仓库列表失败');
      } finally {
        if (!cancelled) {
          setIsAuthorizingScm(false);
        }
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, [connectionsState, repositoriesState]);

  const handleRefreshRepositories = useCallback(() => {
    connectionsState.loadScmConnections({ silent: true })
      .then((latestSources) => {
        if (latestSources.length === 0) {
          repositoriesState.clearScmSelections();
          toast.info('请先完成授权，再刷新仓库列表');
          return;
        }
        return repositoriesState.loadRepositories({
          force: true,
          sources: latestSources
        });
      })
      .catch((error) => {
        console.error('Failed to refresh repositories manually', error);
        toast.error('刷新仓库失败');
      });
  }, [connectionsState, repositoriesState]);

  const handleCreateEnvironment = useCallback(async () => {
    if (!selectedEnvRepo) return;

    const targetOption = repositoriesState.repositoryOptions.find(
      (repo) => repo.fullName === selectedEnvRepo
    );
    if (!targetOption) {
      setCreateDialogOpen(false);
      return;
    }

    repositoriesState.setSelectedRepoKey(targetOption.key);
    setCreateDialogOpen(false);
  }, [repositoriesState, selectedEnvRepo]);

  const handleRevokeScmSource = useCallback(
    async (source: PortalScmSource) => {
      await connectionsState.handleRevokeScmSource(
        source,
        async (sources) => {
          await repositoriesState.loadRepositories({ force: true, sources });
        }
      );
    },
    [connectionsState, repositoriesState]
  );

  return {
    models,
    envRepoSearchId,
    networkAccess,
    setNetworkAccess,
    isAuthorizingScm,
    authDialogProvider,
    setAuthDialogProvider,
    authDialogGitlabBaseUrl,
    setAuthDialogGitlabBaseUrl,
    scmOauthDialogOpen,
    setScmOauthDialogOpen,
    repositoryOptions: repositoriesState.repositoryOptions,
    isRepositoryLoading: repositoriesState.isRepositoryLoading,
    repositoryEmptyMessage: repositoriesState.repositoryEmptyMessage,
    selectedRepoKey: repositoriesState.selectedRepoKey,
    setSelectedRepoKey: repositoriesState.setSelectedRepoKey,
    branchOptions: repositoriesState.branchOptions,
    isBranchLoading: repositoriesState.isBranchLoading,
    selectedBranch: repositoriesState.selectedBranch,
    setSelectedBranch: repositoriesState.setSelectedBranch,
    selectedModel,
    setSelectedModel,
    authorizedScmSources: connectionsState.authorizedScmSources,
    isScmConnectionsLoading: connectionsState.isScmConnectionsLoading,
    revokingScmSourceKey: connectionsState.revokingScmSourceKey,
    isScmConnectionsApiUnavailable:
      connectionsState.isScmConnectionsApiUnavailable,
    selectedRepositoryProvider: repositoriesState.selectedRepositoryProvider,
    selectedRepositoryGitlabBaseUrl:
      repositoriesState.selectedRepositoryGitlabBaseUrl,
    validatedSelectedRepo: repositoriesState.validatedSelectedRepo,
    validatedSelectedBranch: repositoriesState.validatedSelectedBranch,
    createDialogOpen,
    setCreateDialogOpen,
    orgs,
    selectedOrg,
    setSelectedOrg,
    envRepoQuery,
    setEnvRepoQuery,
    filteredEnvRepos,
    selectedEnvRepo,
    setSelectedEnvRepo,
    handleAuthorizeScm,
    handleRefreshRepositories,
    handleCreateEnvironment,
    handleRevokeScmSource
  };
};
