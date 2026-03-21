import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  fetchScmConnections,
  fetchScmRepositories,
  isScmUnauthorizedError,
  revokeScmConnection,
  type ScmConnection
} from '@/lib/scm';
import {
  isScmConnectionsEndpointUnavailable,
  parseScmConnectionSources,
  readRememberedEnterpriseBaseUrls,
  readRememberedProviderHints,
  rememberEnterpriseBaseUrls,
  rememberProviderHints,
  resolveScmApiOptionsFromSource,
  resolveScmSourceLabel,
  buildScmAuthorizationKey,
  toSyntheticScmConnection
} from '@/lib/scm-domain';
import { type PortalScmSource } from '@/business/portal/types';

type UsePortalScmConnectionsOptions = {
  onFilterInvalidRepositoryOptions?: (sources: PortalScmSource[]) => void;
};

export const usePortalScmConnections = ({
  onFilterInvalidRepositoryOptions
}: UsePortalScmConnectionsOptions = {}) => {
  const [scmConnections, setScmConnections] = useState<ScmConnection[]>([]);
  const [isScmConnectionsLoading, setIsScmConnectionsLoading] = useState(true);
  const [isScmConnectionsApiUnavailable, setIsScmConnectionsApiUnavailable] =
    useState(false);
  const [revokingScmSourceKey, setRevokingScmSourceKey] = useState<
    string | null
  >(null);

  const authorizedScmSources = useMemo(
    () => parseScmConnectionSources(scmConnections),
    [scmConnections]
  );

  const probeLegacyScmSources = useCallback(async (): Promise<PortalScmSource[]> => {
    const rememberedProviderHints = readRememberedProviderHints();
    const baseProviders =
      rememberedProviderHints.length > 0
        ? rememberedProviderHints.filter(
            (provider) => provider === 'github' || provider === 'gitlab'
          )
        : (['github', 'gitlab'] as const);
    const rememberedEnterpriseBaseUrls = readRememberedEnterpriseBaseUrls();
    const candidateSources: PortalScmSource[] = [
      ...baseProviders.map((provider) => ({
        key: provider,
        label: resolveScmSourceLabel({ provider }),
        provider
      })),
      ...rememberedEnterpriseBaseUrls.map((baseUrl) => ({
        key: buildScmAuthorizationKey('gitlab_enterprise', baseUrl),
        label: resolveScmSourceLabel({
          provider: 'gitlab_enterprise',
          gitlabBaseUrl: baseUrl
        }),
        provider: 'gitlab_enterprise' as const,
        gitlabBaseUrl: baseUrl
      }))
    ];

    const discovered: PortalScmSource[] = [];
    for (const source of candidateSources) {
      try {
        await fetchScmRepositories(resolveScmApiOptionsFromSource(source));
        discovered.push(source);
      } catch (error) {
        if (!isScmUnauthorizedError(error)) {
          console.error('Failed to probe legacy scm source', source, error);
        }
      }
    }
    rememberProviderHints(discovered);
    rememberEnterpriseBaseUrls(discovered);
    return discovered;
  }, []);

  const loadScmConnections = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      if (!silent) {
        setIsScmConnectionsLoading(true);
      }
      try {
        const connections = await fetchScmConnections();
        setScmConnections(connections);
        setIsScmConnectionsApiUnavailable(false);
        const sources = parseScmConnectionSources(connections);
        rememberProviderHints(sources);
        rememberEnterpriseBaseUrls(sources);
        return sources;
      } catch (error) {
        console.error('Failed to load SCM connections', error);

        const endpointUnavailable = isScmConnectionsEndpointUnavailable(error);
        if (endpointUnavailable) {
          const fallbackSources = await probeLegacyScmSources();
          if (fallbackSources.length > 0) {
            setScmConnections(fallbackSources.map(toSyntheticScmConnection));
            setIsScmConnectionsApiUnavailable(true);
            return fallbackSources;
          }
          setIsScmConnectionsApiUnavailable(true);
          setScmConnections([]);
          if (!silent) {
            toast.info('后端连接中心暂不可用，已切换兼容模式');
          }
          return [] as PortalScmSource[];
        }

        setIsScmConnectionsApiUnavailable(false);
        setScmConnections([]);
        if (!silent) {
          toast.error('加载 SCM 授权状态失败');
        }

        return [] as PortalScmSource[];
      } finally {
        if (!silent) {
          setIsScmConnectionsLoading(false);
        }
      }
    },
    [probeLegacyScmSources]
  );

  const syncInvalidScmSources = useCallback(
    async (sources: PortalScmSource[]) => {
      if (sources.length === 0) return;
      if (isScmConnectionsApiUnavailable) {
        const latestSources = await loadScmConnections({ silent: true });
        onFilterInvalidRepositoryOptions?.(latestSources);
        if (sources.length === 1) {
          toast.info(`${sources[0].label} 授权已失效，请重新绑定`);
        } else {
          toast.info('部分授权已失效，请重新绑定对应平台');
        }
        return;
      }
      await Promise.all(
        sources.map(async (source) => {
          try {
            await revokeScmConnection(resolveScmApiOptionsFromSource(source));
          } catch (error) {
            console.error('Failed to revoke invalid SCM source', source, error);
          }
        })
      );
      const latestSources = await loadScmConnections({ silent: true });
      onFilterInvalidRepositoryOptions?.(latestSources);
      if (sources.length === 1) {
        toast.info(`${sources[0].label} 授权已失效，请重新绑定`);
        return;
      }
      toast.info('部分授权已失效，请重新绑定对应平台');
    },
    [isScmConnectionsApiUnavailable, loadScmConnections, onFilterInvalidRepositoryOptions]
  );

  const handleRevokeScmSource = useCallback(
    async (
      source: PortalScmSource,
      onReloadRepositories?: (sources: PortalScmSource[]) => Promise<void>
    ) => {
      if (revokingScmSourceKey) return;
      if (isScmConnectionsApiUnavailable) {
        toast.info('当前后端版本不支持直接断开，请在平台侧撤销后刷新');
        return;
      }
      setRevokingScmSourceKey(source.key);
      try {
        await revokeScmConnection(resolveScmApiOptionsFromSource(source));
        const latestSources = await loadScmConnections({ silent: true });
        await onReloadRepositories?.(latestSources);
        toast.success(`${source.label} 授权已断开`);
      } catch (error) {
        console.error('Failed to revoke SCM connection', source, error);
        toast.error('断开授权失败，请稍后重试');
      } finally {
        setRevokingScmSourceKey(null);
      }
    },
    [isScmConnectionsApiUnavailable, loadScmConnections, revokingScmSourceKey]
  );

  useEffect(() => {
    void loadScmConnections();
  }, [loadScmConnections]);

  return {
    authorizedScmSources,
    isScmConnectionsLoading,
    isScmConnectionsApiUnavailable,
    revokingScmSourceKey,
    loadScmConnections,
    syncInvalidScmSources,
    handleRevokeScmSource
  };
};
