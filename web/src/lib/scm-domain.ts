import { type PortalScmSource } from '@/business/portal/types';
import { ScmRequestError, type ScmConnection, type ScmProvider } from '@/lib/scm';

export const SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY =
  'openwebpx:scm-enterprise-base-urls';
export const SCM_PROVIDER_HINTS_STORAGE_KEY = 'openwebpx:scm-provider-hints';

export const normalizeGitlabBaseUrl = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return '';
  try {
    return new URL(trimmed).origin.toLowerCase();
  } catch {
    return trimmed.toLowerCase();
  }
};

export const buildScmAuthorizationKey = (
  provider: ScmProvider,
  gitlabBaseUrl: string
) => {
  if (provider === 'github') {
    return provider;
  }
  if (provider === 'gitlab_enterprise') {
    return `${provider}:${normalizeGitlabBaseUrl(gitlabBaseUrl)}`;
  }
  return provider;
};

export const resolveScmSourceLabel = ({
  provider,
  gitlabBaseUrl
}: {
  provider: ScmProvider;
  gitlabBaseUrl?: string;
}) => {
  if (provider === 'github') return 'GitHub';
  if (provider === 'gitlab') return 'GitLab.com';
  if (!gitlabBaseUrl) return 'GitLab 私有';
  try {
    const hostname = new URL(gitlabBaseUrl).hostname;
    return `GitLab 私有 (${hostname})`;
  } catch {
    return `GitLab 私有 (${gitlabBaseUrl})`;
  }
};

const providerOrder: Record<ScmProvider, number> = {
  github: 0,
  gitlab: 1,
  gitlab_enterprise: 2
};

export const parseScmConnectionSources = (connections: ScmConnection[]) => {
  const seen = new Set<string>();
  const sources = connections.reduce<PortalScmSource[]>((acc, connection) => {
    const provider = connection.provider;
    const gitlabBaseUrl =
      provider === 'gitlab_enterprise' ? connection.gitlabBaseUrl : undefined;
    const key =
      connection.connectionKey ||
      buildScmAuthorizationKey(provider, gitlabBaseUrl ?? '');
    if (!key || seen.has(key)) return acc;
    seen.add(key);
    acc.push({
      key,
      label: resolveScmSourceLabel({ provider, gitlabBaseUrl }),
      provider,
      gitlabBaseUrl
    });
    return acc;
  }, []);
  return sources.sort((a, b) => {
    const orderDelta = providerOrder[a.provider] - providerOrder[b.provider];
    if (orderDelta !== 0) return orderDelta;
    return a.label.localeCompare(b.label, 'zh-CN');
  });
};

export const resolveScmApiOptionsFromSource = (source: PortalScmSource) => ({
  provider: source.provider,
  gitlabBaseUrl:
    source.provider === 'gitlab_enterprise' ? source.gitlabBaseUrl : undefined
});

export const isScmConnectionsEndpointUnavailable = (error: unknown) => {
  if (error instanceof ScmRequestError) {
    const normalizedMessage = error.message.toLowerCase();
    if (
      error.status === 400 ||
      error.status === 404 ||
      error.status === 405
    ) {
      return true;
    }
    return (
      error.message.includes('授权连接列表接口') ||
      normalizedMessage.includes('auth_mode') ||
      normalizedMessage.includes('github auth_mode') ||
      error.message.toLowerCase().includes('provider') ||
      error.message.toLowerCase().includes('query')
    );
  }
  if (!(error instanceof Error)) return false;
  const normalized = error.message.toLowerCase();
  return (
    error.message.includes('授权连接列表接口') ||
    error.message.includes('HTTP 400') ||
    error.message.includes('HTTP 404') ||
    error.message.includes('HTTP 405') ||
    normalized.includes('auth_mode') ||
    normalized.includes('provider') ||
    normalized.includes('query')
  );
};

export const getScmOAuthFailureMessage = (
  provider: ScmProvider,
  error?: string
) => {
  const detail = error?.trim();
  if (!detail) return 'OAuth 授权失败';
  const normalized = detail.toLowerCase();
  if (
    provider === 'github' &&
    normalized.includes('oauth state 无效或已过期')
  ) {
    return 'GitHub App 授权已超时，请重新发起授权并尽量在 10 分钟内完成安装或确认。';
  }
  return detail;
};

export const readRememberedEnterpriseBaseUrls = () => {
  if (typeof window === 'undefined') return [] as string[];
  const raw = window.localStorage.getItem(SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY);
  if (!raw) return [] as string[];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [] as string[];
    const normalized = parsed
      .map((item) => (typeof item === 'string' ? normalizeGitlabBaseUrl(item) : ''))
      .filter((item) => item.length > 0);
    return Array.from(new Set(normalized));
  } catch {
    return [] as string[];
  }
};

export const rememberEnterpriseBaseUrls = (sources: PortalScmSource[]) => {
  if (typeof window === 'undefined') return;
  const normalized = sources
    .filter((source) => source.provider === 'gitlab_enterprise')
    .map((source) => normalizeGitlabBaseUrl(source.gitlabBaseUrl ?? ''))
    .filter((item) => item.length > 0);
  const unique = Array.from(new Set(normalized));
  if (unique.length === 0) {
    window.localStorage.removeItem(SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(
    SCM_ENTERPRISE_BASE_URLS_STORAGE_KEY,
    JSON.stringify(unique)
  );
};

export const readRememberedProviderHints = () => {
  if (typeof window === 'undefined') return [] as ScmProvider[];
  const raw = window.localStorage.getItem(SCM_PROVIDER_HINTS_STORAGE_KEY);
  if (!raw) return [] as ScmProvider[];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [] as ScmProvider[];
    const normalized = parsed
      .map((item) => (typeof item === 'string' ? item.trim().toLowerCase() : ''))
      .filter(
        (item): item is ScmProvider =>
          item === 'github' || item === 'gitlab' || item === 'gitlab_enterprise'
      );
    return Array.from(new Set(normalized));
  } catch {
    return [] as ScmProvider[];
  }
};

export const rememberProviderHints = (sources: PortalScmSource[]) => {
  if (typeof window === 'undefined') return;
  const nextProviders = Array.from(
    new Set(
      sources
        .map((source) => source.provider)
        .filter((provider) => provider === 'github' || provider === 'gitlab')
    )
  );
  if (nextProviders.length === 0) {
    return;
  }
  const current = readRememberedProviderHints().filter(
    (provider) => provider === 'github' || provider === 'gitlab'
  );
  const merged = Array.from(new Set([...current, ...nextProviders]));
  window.localStorage.setItem(
    SCM_PROVIDER_HINTS_STORAGE_KEY,
    JSON.stringify(merged)
  );
};

export const toSyntheticScmConnection = (
  source: PortalScmSource
): ScmConnection => ({
  provider: source.provider,
  connectionKey: source.key,
  gitlabBaseUrl: source.gitlabBaseUrl,
  githubAuthMode: source.provider === 'github' ? 'github_app' : undefined,
  expired: false,
  hasRefreshToken: false
});

export const buildRepositoryOptionKey = (
  sourceKey: string,
  repositoryFullName: string
) => `${sourceKey}::${repositoryFullName}`;
