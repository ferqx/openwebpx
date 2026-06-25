import { authFetch } from '@/lib/auth';

export type ScmProvider = 'github' | 'gitlab' | 'gitlab_enterprise';
export type ScmGithubAuthMode = 'github_app';

export type ScmRepository = {
  id: string;
  fullName: string;
  defaultBranch?: string;
};

export type ScmConnection = {
  provider: ScmProvider;
  connectionKey: string;
  gitlabBaseUrl?: string;
  githubAuthMode?: ScmGithubAuthMode;
  updatedAt?: number;
  expiresAt?: number;
  expired: boolean;
  hasRefreshToken: boolean;
};

type ProviderApiType = 'github' | 'gitlab';

type ScmApiOptions = {
  provider: ScmProvider;
  gitlabBaseUrl?: string;
};

type FetchBranchesOptions = ScmApiOptions & {
  repository: string;
};

const SCM_OAUTH_PENDING_STORAGE_KEY = 'sandbox-agent:scm-oauth-pending';
const SCM_OAUTH_RESULT_STORAGE_KEY = 'sandbox-agent:scm-oauth-result';

export type ScmOauthResult = {
  ok: boolean;
  provider: ScmProvider;
  error?: string;
};

export type ScmOauthSessionState = {
  provider: ScmProvider;
  gitlabBaseUrl?: string;
  returnTo: string;
};

export class ScmRequestError extends Error {
  readonly status?: number;

  constructor(message: string, options?: { status?: number }) {
    super(message);
    this.name = 'ScmRequestError';
    this.status = options?.status;
  }
}

type ScmEndpointType =
  | 'repositories'
  | 'branches'
  | 'oauthAuthorize'
  | 'oauthCallback'
  | 'connections'
  | 'connectionValidate'
  | 'connectionRevoke';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const SCM_ENDPOINT_ENV_KEYS: Record<ScmEndpointType, string> = {
  repositories: 'VITE_SCM_REPOSITORIES_ENDPOINT',
  branches: 'VITE_SCM_BRANCHES_ENDPOINT',
  oauthAuthorize: 'VITE_SCM_OAUTH_AUTHORIZE_ENDPOINT',
  oauthCallback: 'VITE_SCM_OAUTH_CALLBACK_ENDPOINT',
  connections: 'VITE_SCM_CONNECTIONS_ENDPOINT',
  connectionValidate: 'VITE_SCM_CONNECTION_VALIDATE_ENDPOINT',
  connectionRevoke: 'VITE_SCM_CONNECTION_REVOKE_ENDPOINT'
};

const DEFAULT_SCM_ENDPOINTS: Record<ScmEndpointType, string[]> = {
  repositories: [
    '/api/integrations/scm/repositories',
    '/api/scm/repositories',
    '/api/custom/integrations/scm/repositories'
  ],
  branches: [
    '/api/integrations/scm/branches',
    '/api/scm/branches',
    '/api/custom/integrations/scm/branches'
  ],
  oauthAuthorize: [
    '/api/integrations/scm/oauth/authorize',
    '/api/scm/oauth/authorize',
    '/api/custom/integrations/scm/oauth/authorize'
  ],
  oauthCallback: [
    '/api/integrations/scm/oauth/callback',
    '/api/scm/oauth/callback',
    '/api/custom/integrations/scm/oauth/callback'
  ],
  connections: [
    '/api/integrations/scm/connections',
    '/api/scm/connections',
    '/api/custom/integrations/scm/connections'
  ],
  connectionValidate: [
    '/api/integrations/scm/connections/validate',
    '/api/scm/connections/validate',
    '/api/custom/integrations/scm/connections/validate'
  ],
  connectionRevoke: [
    '/api/integrations/scm/connections',
    '/api/scm/connections',
    '/api/custom/integrations/scm/connections'
  ]
};

const endpointNotFoundMessage = (type: ScmEndpointType) => {
  if (type === 'repositories') {
    return '后端未提供 SCM 仓库列表接口，请先完成服务端集成';
  }
  if (type === 'branches') {
    return '后端未提供 SCM 分支列表接口，请先完成服务端集成';
  }
  if (type === 'oauthAuthorize') {
    return '后端未提供 SCM OAuth 授权接口，请先完成服务端集成';
  }
  if (type === 'oauthCallback') {
    return '后端未提供 SCM OAuth 回调接口，请先完成服务端集成';
  }
  if (type === 'connections') {
    return '后端未提供 SCM 授权连接列表接口，请先升级后端服务';
  }
  if (type === 'connectionValidate') {
    return '后端未提供 SCM 授权验证接口，请先升级后端服务';
  }
  return '后端未提供 SCM 断开授权接口，请先升级后端服务';
};

const parseJsonSafely = async (response: Response) => {
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
};

const extractPayloadErrorMessage = (payload: unknown): string | undefined => {
  if (!isRecord(payload)) return undefined;
  const candidates = [payload.message, payload.detail, payload.error];
  const found = candidates.find((item) => typeof item === 'string');
  if (typeof found === 'string' && found.trim()) {
    return found.trim();
  }
  const nestedData = payload.data;
  if (isRecord(nestedData)) {
    return extractPayloadErrorMessage(nestedData);
  }
  return undefined;
};

const assertPayloadOk = (payload: unknown, fallback: string) => {
  if (!isRecord(payload) || payload.ok !== false) return;
  throw new ScmRequestError(
    extractPayloadErrorMessage(payload) ?? fallback
  );
};

const toProviderApiType = (provider: ScmProvider): ProviderApiType =>
  provider === 'github' ? 'github' : 'gitlab';

const resolveConnectionProvider = ({
  provider,
  isEnterprise
}: {
  provider: string;
  isEnterprise: boolean;
}): ScmProvider | undefined => {
  const normalizedProvider = provider.trim().toLowerCase();
  if (normalizedProvider === 'github') return 'github';
  if (normalizedProvider !== 'gitlab') return undefined;
  return isEnterprise ? 'gitlab_enterprise' : 'gitlab';
};

const coerceNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
};

const resolveRepositoryName = (value: unknown): string | undefined => {
  if (!isRecord(value)) return undefined;
  const candidates = [
    value.full_name,
    value.path_with_namespace,
    value.fullName,
    value.name
  ];
  const found = candidates.find((item) => typeof item === 'string');
  if (!found || typeof found !== 'string') return undefined;
  const trimmed = found.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const resolveRepositoryId = (value: unknown): string => {
  if (!isRecord(value)) return '';
  const idValue = value.id;
  if (typeof idValue === 'string') return idValue;
  if (typeof idValue === 'number') return String(idValue);
  return '';
};

const resolveDefaultBranch = (value: unknown): string | undefined => {
  if (!isRecord(value)) return undefined;
  const candidates = [value.default_branch, value.defaultBranch];
  const found = candidates.find((item) => typeof item === 'string');
  if (!found || typeof found !== 'string') return undefined;
  const trimmed = found.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const getErrorMessage = async (response: Response) => {
  const data = await parseJsonSafely(response);
  const payloadMessage = extractPayloadErrorMessage(data);
  if (payloadMessage) {
    return payloadMessage;
  }
  const fallback = await response.text().catch(() => '');
  return fallback || `HTTP ${response.status}`;
};

const SCM_UNAUTHORIZED_HINTS = [
  '请先完成 oauth 授权',
  '授权令牌不存在',
  'oauth state 与当前用户不匹配',
  'unauthorized',
  'forbidden',
  'http 401',
  'http 403'
];

export const isScmUnauthorizedError = (error: unknown) => {
  if (error instanceof ScmRequestError) {
    if (error.status === 401 || error.status === 403) {
      return true;
    }
    const normalizedMessage = error.message.trim().toLowerCase();
    return SCM_UNAUTHORIZED_HINTS.some((hint) =>
      normalizedMessage.includes(hint)
    );
  }
  if (!(error instanceof Error)) return false;
  const normalizedMessage = error.message.trim().toLowerCase();
  return SCM_UNAUTHORIZED_HINTS.some((hint) =>
    normalizedMessage.includes(hint)
  );
};

const normalizeBaseUrl = (value?: string) => {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  try {
    const url = new URL(trimmed);
    return url.origin;
  } catch {
    return undefined;
  }
};

export const isValidScmBaseUrl = (value: string) =>
  Boolean(normalizeBaseUrl(value));

const getEnvScmEndpoint = (key: string) => {
  const env = (import.meta.env ||
    (typeof process !== 'undefined' ? process.env : undefined) ||
    {}) as unknown as Record<string, unknown>;
  const raw = env[key];
  if (typeof raw !== 'string') return undefined;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const buildEndpointCandidates = (
  type: ScmEndpointType,
  params?: URLSearchParams
) => {
  const candidates = [
    getEnvScmEndpoint(SCM_ENDPOINT_ENV_KEYS[type]),
    ...DEFAULT_SCM_ENDPOINTS[type]
  ].filter((item): item is string => Boolean(item));
  const seen = new Set<string>();
  const resolved: string[] = [];

  candidates.forEach((path) => {
    const url = new URL(path, window.location.origin);
    if (params) {
      params.forEach((value, key) => {
        url.searchParams.set(key, value);
      });
    }
    const normalized = url.toString();
    if (seen.has(normalized)) return;
    seen.add(normalized);
    resolved.push(normalized);
  });

  return resolved;
};

const buildScmParams = ({
  provider,
  gitlabBaseUrl,
  extras,
  includeEnterpriseFlag = false
}: {
  provider: ScmProvider;
  gitlabBaseUrl?: string;
  extras?: Record<string, string | undefined>;
  includeEnterpriseFlag?: boolean;
}) => {
  const params = new URLSearchParams();
  params.set('provider', toProviderApiType(provider));
  if (provider === 'github') {
    params.set('auth_mode', 'github_app');
    // Backward compatibility: some backends still parse github_auth_mode.
    params.set('github_auth_mode', 'github_app');
  }

  if (extras) {
    Object.entries(extras).forEach(([key, value]) => {
      if (!value) return;
      params.set(key, value);
    });
  }

  const normalizedBaseUrl = normalizeBaseUrl(gitlabBaseUrl);
  if (provider === 'gitlab_enterprise' && normalizedBaseUrl) {
    params.set('gitlab_base_url', normalizedBaseUrl);
    if (includeEnterpriseFlag) {
      params.set('is_enterprise', 'true');
    }
  }

  return params;
};

const fetchFromCandidateEndpoints = async ({
  type,
  params,
  init,
  skipStatusCodes = [404]
}: {
  type: ScmEndpointType;
  params?: URLSearchParams;
  init: RequestInit;
  skipStatusCodes?: number[];
}) => {
  const candidateUrls = buildEndpointCandidates(type, params);
  let lastNetworkError: string | undefined;
  let lastResponse: Response | undefined;

  for (const requestUrl of candidateUrls) {
    try {
      const response = await authFetch(requestUrl, init);
      if (skipStatusCodes.includes(response.status)) {
        lastResponse = response;
        continue;
      }
      return { response, requestUrl };
    } catch (error) {
      lastNetworkError =
        error instanceof Error ? error.message : '网络请求失败';
    }
  }

  if (lastNetworkError) {
    throw new ScmRequestError(lastNetworkError);
  }

  if (lastResponse && !lastResponse.ok) {
    throw new ScmRequestError(await getErrorMessage(lastResponse), {
      status: lastResponse.status
    });
  }

  throw new ScmRequestError(endpointNotFoundMessage(type));
};

const extractAuthorizeUrlFromPayload = (payload: unknown): string | undefined => {
  if (!isRecord(payload)) return undefined;
  const keyCandidates = [
    'authorize_url',
    'authorization_url',
    'auth_url',
    'redirect_url',
    'url'
  ] as const;
  for (const key of keyCandidates) {
    const value = payload[key];
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  const nestedData = payload.data;
  if (isRecord(nestedData)) {
    return extractAuthorizeUrlFromPayload(nestedData);
  }
  return undefined;
};

const resolveScmAuthorizeUrl = async ({
  provider,
  redirectUri,
  gitlabBaseUrl
}: {
  provider: ScmProvider;
  redirectUri: string;
  gitlabBaseUrl?: string;
}) => {
  const params = buildScmParams({
    provider,
    gitlabBaseUrl,
    includeEnterpriseFlag: true,
    extras: {
      redirect_uri: redirectUri,
      origin: window.location.origin,
      response_mode: 'json'
    }
  });

  const { response, requestUrl } = await fetchFromCandidateEndpoints({
    type: 'oauthAuthorize',
    params,
    init: {
      method: 'GET',
      credentials: 'include'
    },
    skipStatusCodes: [404, 405]
  });

  if (!response.ok) {
    throw new ScmRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }

  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, 'SCM 授权失败');
  const authorizeUrl = extractAuthorizeUrlFromPayload(payload);
  if (authorizeUrl) return authorizeUrl;
  return requestUrl;
};

export const fetchScmRepositories = async ({
  provider,
  gitlabBaseUrl
}: ScmApiOptions): Promise<ScmRepository[]> => {
  const params = buildScmParams({ provider, gitlabBaseUrl });
  const { response } = await fetchFromCandidateEndpoints({
    type: 'repositories',
    params,
    init: {
      method: 'GET',
      credentials: 'include'
    }
  });

  if (!response.ok) {
    throw new ScmRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }

  const data = await parseJsonSafely(response);
  assertPayloadOk(data, '仓库列表查询失败');
  const rawItems =
    isRecord(data) && Array.isArray(data.repositories)
      ? data.repositories
      : Array.isArray(data)
        ? data
        : [];

  return rawItems.reduce<ScmRepository[]>((repositories, item) => {
    const fullName = resolveRepositoryName(item);
    if (!fullName) return repositories;

    const defaultBranch = resolveDefaultBranch(item);
    repositories.push(
      defaultBranch
        ? { id: resolveRepositoryId(item), fullName, defaultBranch }
        : { id: resolveRepositoryId(item), fullName }
    );
    return repositories;
  }, []);
};

export const fetchScmConnections = async (): Promise<ScmConnection[]> => {
  const { response } = await fetchFromCandidateEndpoints({
    type: 'connections',
    init: {
      method: 'GET',
      credentials: 'include'
    },
    skipStatusCodes: [404, 405]
  });

  if (!response.ok) {
    throw new ScmRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }

  const data = await parseJsonSafely(response);
  assertPayloadOk(data, 'SCM 授权连接列表查询失败');
  const rawItems =
    isRecord(data) && Array.isArray(data.connections)
      ? data.connections
      : Array.isArray(data)
        ? data
        : [];

  return rawItems.reduce<ScmConnection[]>((connections, item) => {
    if (!isRecord(item)) return connections;
    const provider = resolveConnectionProvider({
      provider: typeof item.provider === 'string' ? item.provider : '',
      isEnterprise: Boolean(item.is_enterprise)
    });
    if (!provider) return connections;
    const gitlabBaseUrl =
      typeof item.gitlab_base_url === 'string' && item.gitlab_base_url.trim()
        ? item.gitlab_base_url.trim()
        : undefined;
    const connectionKey =
      typeof item.connection_key === 'string' && item.connection_key.trim()
        ? item.connection_key.trim()
        : provider === 'gitlab_enterprise' && gitlabBaseUrl
          ? `gitlab_enterprise:${gitlabBaseUrl.toLowerCase()}`
          : provider;
    const githubAuthMode =
      provider === 'github' ? 'github_app' : undefined;

    connections.push({
      provider,
      connectionKey,
      gitlabBaseUrl,
      githubAuthMode,
      updatedAt: coerceNumber(item.updated_at),
      expiresAt: coerceNumber(item.expires_at),
      expired: Boolean(item.expired),
      hasRefreshToken: Boolean(item.has_refresh_token)
    });
    return connections;
  }, []);
};

export const fetchScmBranches = async ({
  provider,
  repository,
  gitlabBaseUrl
}: FetchBranchesOptions): Promise<string[]> => {
  const params = buildScmParams({
    provider,
    gitlabBaseUrl,
    extras: { repository }
  });
  const { response } = await fetchFromCandidateEndpoints({
    type: 'branches',
    params,
    init: {
      method: 'GET',
      credentials: 'include'
    }
  });

  if (!response.ok) {
    throw new ScmRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }

  const data = await parseJsonSafely(response);
  assertPayloadOk(data, '分支列表查询失败');
  const rawItems =
    isRecord(data) && Array.isArray(data.branches)
      ? data.branches
      : Array.isArray(data)
        ? data
        : [];

  return rawItems
    .map((item) => {
      if (typeof item === 'string') return item;
      if (isRecord(item) && typeof item.name === 'string') return item.name;
      return undefined;
    })
    .filter((item): item is string => Boolean(item))
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
};

export const revokeScmConnection = async ({
  provider,
  gitlabBaseUrl
}: ScmApiOptions): Promise<void> => {
  const params = buildScmParams({
    provider,
    gitlabBaseUrl,
    includeEnterpriseFlag: true
  });
  const { response } = await fetchFromCandidateEndpoints({
    type: 'connectionRevoke',
    params,
    init: {
      method: 'DELETE',
      credentials: 'include'
    },
    skipStatusCodes: [404, 405]
  });
  if (!response.ok) {
    throw new ScmRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, 'SCM 断开授权失败');
};

export const validateScmConnection = async ({
  provider,
  gitlabBaseUrl
}: ScmApiOptions): Promise<{ valid: boolean; revoked: boolean; error?: string }> => {
  const params = buildScmParams({
    provider,
    gitlabBaseUrl,
    includeEnterpriseFlag: true
  });
  const { response } = await fetchFromCandidateEndpoints({
    type: 'connectionValidate',
    params,
    init: {
      method: 'GET',
      credentials: 'include'
    },
    skipStatusCodes: [404, 405]
  });
  if (!response.ok) {
    throw new ScmRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, 'SCM 授权验证失败');
  if (!isRecord(payload)) {
    return { valid: false, revoked: false, error: 'SCM 授权验证返回异常' };
  }
  return {
    valid: Boolean(payload.valid),
    revoked: Boolean(payload.revoked),
    error: typeof payload.error === 'string' ? payload.error : undefined
  };
};

const readSessionStorageJson = (key: string) => {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
};

const writeSessionStorageJson = (key: string, value: unknown) => {
  if (typeof window === 'undefined') return;
  window.sessionStorage.setItem(key, JSON.stringify(value));
};

export const getScmOAuthSessionState = (): ScmOauthSessionState | null => {
  const data = readSessionStorageJson(SCM_OAUTH_PENDING_STORAGE_KEY);
  if (!isRecord(data)) return null;
  const provider = data.provider;
  const returnTo = data.returnTo;
  if (
    (provider !== 'github' &&
      provider !== 'gitlab' &&
      provider !== 'gitlab_enterprise') ||
    typeof returnTo !== 'string' ||
    !returnTo.startsWith('/')
  ) {
    return null;
  }
  return {
    provider,
    returnTo,
    gitlabBaseUrl:
      typeof data.gitlabBaseUrl === 'string' ? data.gitlabBaseUrl : undefined
  };
};

export const clearScmOAuthSessionState = () => {
  if (typeof window === 'undefined') return;
  window.sessionStorage.removeItem(SCM_OAUTH_PENDING_STORAGE_KEY);
};

export const persistScmOAuthResult = (
  result: ScmOauthResult & { gitlabBaseUrl?: string }
) => {
  writeSessionStorageJson(SCM_OAUTH_RESULT_STORAGE_KEY, result);
};

export const consumeScmOAuthResult = (): (ScmOauthResult & {
  gitlabBaseUrl?: string;
}) | null => {
  const data = readSessionStorageJson(SCM_OAUTH_RESULT_STORAGE_KEY);
  if (typeof window !== 'undefined') {
    window.sessionStorage.removeItem(SCM_OAUTH_RESULT_STORAGE_KEY);
  }
  if (!isRecord(data)) return null;
  const provider = data.provider;
  if (
    provider !== 'github' &&
    provider !== 'gitlab' &&
    provider !== 'gitlab_enterprise'
  ) {
    return null;
  }
  return {
    ok: Boolean(data.ok),
    provider,
    error: typeof data.error === 'string' ? data.error : undefined,
    gitlabBaseUrl:
      typeof data.gitlabBaseUrl === 'string' ? data.gitlabBaseUrl : undefined
  };
};

export const startScmOAuthRedirect = async ({
  provider,
  redirectUri,
  returnTo,
  gitlabBaseUrl
}: {
  provider: ScmProvider;
  redirectUri: string;
  returnTo: string;
  gitlabBaseUrl?: string;
}): Promise<void> => {
  const authorizeUrl = await resolveScmAuthorizeUrl({
    provider,
    redirectUri,
    gitlabBaseUrl
  });
  writeSessionStorageJson(SCM_OAUTH_PENDING_STORAGE_KEY, {
    provider,
    returnTo,
    gitlabBaseUrl
  });
  window.location.assign(authorizeUrl);
};

export const completeScmOAuthCallback = async (
  query: URLSearchParams
): Promise<{ ok: boolean; error?: string }> => {
  const body = JSON.stringify({
    params: Object.fromEntries(query.entries()),
    redirect_uri: `${window.location.origin}/oauth/scm/callback`
  });
  const callbackCandidates = buildEndpointCandidates('oauthCallback');
  let lastNetworkError: string | undefined;

  for (const callbackUrl of callbackCandidates) {
    try {
      const response = await authFetch(callbackUrl, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json'
        },
        body
      });
      if (response.status === 404 || response.status === 405) {
        continue;
      }
      if (!response.ok) {
        return { ok: false, error: await getErrorMessage(response) };
      }

      const data = await parseJsonSafely(response);
      if (isRecord(data) && data.ok === false) {
        return {
          ok: false,
          error: typeof data.error === 'string' ? data.error : '授权失败'
        };
      }
      return { ok: true };
    } catch (error) {
      lastNetworkError =
        error instanceof Error ? error.message : 'OAuth 回调请求失败';
    }
  }

  for (const callbackUrl of callbackCandidates) {
    try {
      const response = await authFetch(
        `${callbackUrl}?${new URLSearchParams(Object.fromEntries(query.entries()))}`,
        {
          method: 'GET',
          credentials: 'include'
        }
      );
      if (response.status === 404) {
        continue;
      }
      if (!response.ok) {
        return { ok: false, error: await getErrorMessage(response) };
      }
      const data = await parseJsonSafely(response);
      if (isRecord(data) && data.ok === false) {
        return {
          ok: false,
          error: typeof data.error === 'string' ? data.error : '授权失败'
        };
      }
      return { ok: true };
    } catch (error) {
      lastNetworkError =
        error instanceof Error ? error.message : 'OAuth 回调请求失败';
    }
  }

  if (lastNetworkError) {
    return { ok: false, error: lastNetworkError };
  }
  return { ok: false, error: endpointNotFoundMessage('oauthCallback') };
};
