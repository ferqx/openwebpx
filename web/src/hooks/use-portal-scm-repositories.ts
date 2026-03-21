import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchScmBranches,
  fetchScmRepositories,
  isScmUnauthorizedError,
  isValidScmBaseUrl,
  validateScmConnection
} from '@/lib/scm';
import {
  buildRepositoryOptionKey,
  resolveScmApiOptionsFromSource
} from '@/lib/scm-domain';
import {
  type PortalScmRepositoryOption,
  type PortalScmSource
} from '@/business/portal/types';

type UsePortalScmRepositoriesOptions = {
  authorizedScmSources: PortalScmSource[];
  isScmConnectionsLoading: boolean;
  isScmConnectionsApiUnavailable: boolean;
  onSyncInvalidSources: (sources: PortalScmSource[]) => Promise<void>;
};

export const usePortalScmRepositories = ({
  authorizedScmSources,
  isScmConnectionsLoading,
  isScmConnectionsApiUnavailable,
  onSyncInvalidSources
}: UsePortalScmRepositoriesOptions) => {
  const [repositoryOptions, setRepositoryOptions] = useState<
    PortalScmRepositoryOption[]
  >([]);
  const [branchOptions, setBranchOptions] = useState<string[]>([]);
  const [isRepositoryLoading, setIsRepositoryLoading] = useState(false);
  const [isBranchLoading, setIsBranchLoading] = useState(false);
  const [selectedRepoKey, setSelectedRepoKey] = useState('');
  const [selectedBranch, setSelectedBranch] = useState('');

  const hasAnyScmAuthorized = authorizedScmSources.length > 0;
  const selectedRepositoryOption = useMemo(
    () => repositoryOptions.find((option) => option.key === selectedRepoKey),
    [repositoryOptions, selectedRepoKey]
  );
  const selectedRepositorySource = selectedRepositoryOption?.source;
  const selectedRepositoryProvider = selectedRepositorySource?.provider;
  const selectedRepositoryGitlabBaseUrl = selectedRepositorySource?.gitlabBaseUrl;
  const validatedSelectedRepo = selectedRepositoryOption?.fullName ?? '';
  const validatedSelectedBranch = useMemo(
    () => (branchOptions.includes(selectedBranch) ? selectedBranch : ''),
    [branchOptions, selectedBranch]
  );
  const repositoryNames = useMemo(
    () => Array.from(new Set(repositoryOptions.map((repo) => repo.fullName))),
    [repositoryOptions]
  );
  const repositoryEmptyMessage = useMemo(() => {
    if (isScmConnectionsLoading || isRepositoryLoading) return '正在加载仓库...';
    if (hasAnyScmAuthorized) return '当前授权范围内未找到仓库';
    return '未找到仓库，请先完成 GitHub/GitLab 授权';
  }, [hasAnyScmAuthorized, isRepositoryLoading, isScmConnectionsLoading]);

  const clearScmSelections = useCallback(() => {
    setRepositoryOptions([]);
    setSelectedRepoKey('');
    setBranchOptions([]);
    setSelectedBranch('');
  }, []);

  const filterRepositoryOptionsBySources = useCallback(
    (sources: PortalScmSource[]) => {
      setRepositoryOptions((prev) =>
        prev.filter((option) =>
          sources.some((source) => source.key === option.source.key)
        )
      );
    },
    []
  );

  const loadRepositories = useCallback(
    async ({
      force = false,
      sources
    }: { force?: boolean; sources?: PortalScmSource[] } = {}) => {
      const activeSources = sources ?? authorizedScmSources;
      if (activeSources.length === 0) {
        clearScmSelections();
        return;
      }
      if (!force && !hasAnyScmAuthorized) return;

      setIsRepositoryLoading(true);
      try {
        const staleSourceMap = new Map<string, PortalScmSource>();
        const groupedRepositories = await Promise.all(
          activeSources.map(async (source) => {
            if (!isScmConnectionsApiUnavailable) {
              try {
                const validation = await validateScmConnection(
                  resolveScmApiOptionsFromSource(source)
                );
                if (!validation.valid || validation.revoked) {
                  staleSourceMap.set(source.key, source);
                  return [];
                }
              } catch (error) {
                console.error('Failed to validate SCM connection', source, error);
              }
            }

            try {
              const repositories = await fetchScmRepositories(
                resolveScmApiOptionsFromSource(source)
              );
              return repositories.map<PortalScmRepositoryOption>((repo) => ({
                key: buildRepositoryOptionKey(source.key, repo.fullName),
                fullName: repo.fullName,
                defaultBranch: repo.defaultBranch,
                source
              }));
            } catch (error) {
              console.error(
                'Failed to load repositories for source',
                source,
                error
              );
              if (isScmUnauthorizedError(error)) {
                staleSourceMap.set(source.key, source);
              }
              return [];
            }
          })
        );

        const staleSources = Array.from(staleSourceMap.values());
        if (staleSources.length > 0) {
          await onSyncInvalidSources(staleSources);
        }

        const mergedRepositories = groupedRepositories.flat();
        setRepositoryOptions(mergedRepositories);
        setSelectedRepoKey((prev) => {
          if (prev && mergedRepositories.some((repo) => repo.key === prev)) {
            return prev;
          }
          return '';
        });
      } finally {
        setIsRepositoryLoading(false);
      }
    },
    [
      authorizedScmSources,
      clearScmSelections,
      hasAnyScmAuthorized,
      isScmConnectionsApiUnavailable,
      onSyncInvalidSources
    ]
  );

  useEffect(() => {
    if (isScmConnectionsLoading) return;
    loadRepositories().catch((error) => {
      console.error('Failed to refresh repositories', error);
    });
  }, [isScmConnectionsLoading, loadRepositories]);

  useEffect(() => {
    if (!selectedRepositorySource) {
      setBranchOptions([]);
      setSelectedBranch('');
      return;
    }
    if (!validatedSelectedRepo) {
      setBranchOptions([]);
      setSelectedBranch('');
      return;
    }
    if (
      selectedRepositorySource.provider === 'gitlab_enterprise' &&
      !isValidScmBaseUrl(selectedRepositorySource.gitlabBaseUrl ?? '')
    ) {
      setBranchOptions([]);
      setSelectedBranch('');
      return;
    }
    let isCancelled = false;
    setBranchOptions([]);
    setSelectedBranch('');
    setIsBranchLoading(true);
    fetchScmBranches({
      provider: selectedRepositorySource.provider,
      repository: validatedSelectedRepo,
      gitlabBaseUrl: selectedRepositorySource.gitlabBaseUrl
    })
      .then((branches) => {
        if (isCancelled) return;
        setBranchOptions(branches);
      })
      .catch((error) => {
        if (isCancelled) return;
        console.error('Failed to load branches', error);
        if (isScmUnauthorizedError(error)) {
          void onSyncInvalidSources([selectedRepositorySource]);
          setBranchOptions([]);
          setSelectedBranch('');
          return;
        }
        setBranchOptions(['main']);
      })
      .finally(() => {
        if (!isCancelled) setIsBranchLoading(false);
      });
    return () => {
      isCancelled = true;
    };
  }, [onSyncInvalidSources, selectedRepositorySource, validatedSelectedRepo]);

  return {
    repositoryOptions,
    branchOptions,
    isRepositoryLoading,
    isBranchLoading,
    selectedRepoKey,
    setSelectedRepoKey,
    selectedBranch,
    setSelectedBranch,
    selectedRepositoryProvider,
    selectedRepositoryGitlabBaseUrl,
    validatedSelectedRepo,
    validatedSelectedBranch,
    repositoryNames,
    repositoryEmptyMessage,
    clearScmSelections,
    loadRepositories,
    filterRepositoryOptionsBySources
  };
};
