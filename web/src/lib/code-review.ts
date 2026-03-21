import { authFetch } from '@/lib/auth';

export type CodeReviewTrigger = 'pr_open' | 'push';
export type CodeReviewAutoReview = 'follow_global' | 'enabled' | 'disabled';
export type CodeReviewProvider = 'github' | 'gitlab';

export type CodeReviewGlobalSettings = {
  autoReviewEnabled: boolean;
  defaultTrigger: CodeReviewTrigger;
  updatedAt?: number;
  updatedBy?: string;
};

export type CodeReviewRepositorySetting = {
  provider: CodeReviewProvider;
  repository: string;
  gitlabBaseUrl?: string;
  autoReview: CodeReviewAutoReview;
  trigger: CodeReviewTrigger | 'follow_global';
  updatedAt?: number;
  updatedBy?: string;
};

export type CodeReviewWebhookManualSetup = {
  provider: CodeReviewProvider;
  repository: string;
  events?: string[];
  payloadUrl?: string;
  secret?: string;
  hint?: string;
};

export type CodeReviewWebhookSyncResult = {
  enabled: boolean;
  ok: boolean;
  mode: 'auto' | 'manual';
  message: string;
  provider: CodeReviewProvider;
  repository: string;
  webhookUrl?: string;
  manualSetup?: CodeReviewWebhookManualSetup;
};

export class CodeReviewRequestError extends Error {
  readonly status?: number;

  constructor(message: string, options?: { status?: number }) {
    super(message);
    this.name = 'CodeReviewRequestError';
    this.status = options?.status;
  }
}

type EndpointType = 'settings' | 'globalSettings' | 'repoSettings';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const ENDPOINT_ENV_KEYS: Record<EndpointType, string> = {
  settings: 'VITE_CODE_REVIEW_SETTINGS_ENDPOINT',
  globalSettings: 'VITE_CODE_REVIEW_GLOBAL_SETTINGS_ENDPOINT',
  repoSettings: 'VITE_CODE_REVIEW_REPO_SETTINGS_ENDPOINT'
};

const DEFAULT_ENDPOINTS: Record<EndpointType, string[]> = {
  settings: [
    '/api/integrations/code-review/settings',
    '/api/code-review/settings',
    '/api/custom/integrations/code-review/settings'
  ],
  globalSettings: [
    '/api/integrations/code-review/settings/global',
    '/api/code-review/settings/global',
    '/api/custom/integrations/code-review/settings/global'
  ],
  repoSettings: [
    '/api/integrations/code-review/settings/repositories',
    '/api/code-review/settings/repositories',
    '/api/custom/integrations/code-review/settings/repositories'
  ]
};

const endpointNotFoundMessage = (type: EndpointType) => {
  if (type === 'settings') {
    return '后端未提供代码审查设置查询接口，请先升级后端服务';
  }
  if (type === 'globalSettings') {
    return '后端未提供代码审查全局设置接口，请先升级后端服务';
  }
  return '后端未提供代码审查仓库设置接口，请先升级后端服务';
};

const getEnvEndpoint = (key: string) => {
  const env = import.meta.env as unknown as Record<string, unknown>;
  const raw = env[key];
  if (typeof raw !== 'string') return undefined;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const buildEndpointCandidates = (type: EndpointType, params?: URLSearchParams) => {
  const candidates = [
    getEnvEndpoint(ENDPOINT_ENV_KEYS[type]),
    ...DEFAULT_ENDPOINTS[type]
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
  const nested = payload.data;
  if (isRecord(nested)) {
    return extractPayloadErrorMessage(nested);
  }
  return undefined;
};

const getErrorMessage = async (response: Response) => {
  const payload = await parseJsonSafely(response);
  const payloadMessage = extractPayloadErrorMessage(payload);
  if (payloadMessage) return payloadMessage;
  const fallback = await response.text().catch(() => '');
  return fallback || `HTTP ${response.status}`;
};

const assertPayloadOk = (payload: unknown, fallback: string) => {
  if (!isRecord(payload) || payload.ok !== false) return;
  throw new CodeReviewRequestError(
    extractPayloadErrorMessage(payload) ?? fallback
  );
};

const coerceNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
};

const normalizeProvider = (value: unknown): CodeReviewProvider | undefined => {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim().toLowerCase();
  if (normalized === 'github') return 'github';
  if (normalized === 'gitlab') return 'gitlab';
  return undefined;
};

const normalizeTrigger = (value: unknown): CodeReviewTrigger | undefined => {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim().toLowerCase();
  if (normalized === 'pr_open') return 'pr_open';
  if (normalized === 'push') return 'push';
  return undefined;
};

const normalizeAutoReview = (value: unknown): CodeReviewAutoReview | undefined => {
  if (typeof value !== 'string') return undefined;
  const normalized = value.trim().toLowerCase();
  if (
    normalized === 'follow_global' ||
    normalized === 'enabled' ||
    normalized === 'disabled'
  ) {
    return normalized;
  }
  return undefined;
};

const normalizeGitlabBaseUrl = (value: unknown): string | undefined => {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  return value.trim();
};

const fetchFromCandidateEndpoints = async ({
  type,
  params,
  init,
  skipStatusCodes = [404]
}: {
  type: EndpointType;
  params?: URLSearchParams;
  init: RequestInit;
  skipStatusCodes?: number[];
}) => {
  const candidateUrls = buildEndpointCandidates(type, params);
  let lastNetworkError: string | undefined;

  for (const requestUrl of candidateUrls) {
    try {
      const response = await authFetch(requestUrl, init);
      if (skipStatusCodes.includes(response.status)) {
        continue;
      }
      return { response, requestUrl };
    } catch (error) {
      lastNetworkError = error instanceof Error ? error.message : '网络请求失败';
    }
  }

  if (lastNetworkError) {
    throw new CodeReviewRequestError(lastNetworkError);
  }
  throw new CodeReviewRequestError(endpointNotFoundMessage(type));
};

const normalizeRepositorySetting = (
  value: unknown
): CodeReviewRepositorySetting | undefined => {
  if (!isRecord(value)) return undefined;
  const provider = normalizeProvider(value.provider);
  if (!provider) return undefined;
  const repository =
    typeof value.repository === 'string' ? value.repository.trim() : '';
  if (!repository) return undefined;

  const autoReview = normalizeAutoReview(value.auto_review) ?? 'follow_global';
  const triggerRaw =
    typeof value.trigger === 'string' ? value.trigger.trim().toLowerCase() : '';
  const trigger =
    triggerRaw === 'follow_global'
      ? 'follow_global'
      : (normalizeTrigger(triggerRaw) ?? 'follow_global');

  return {
    provider,
    repository,
    gitlabBaseUrl: normalizeGitlabBaseUrl(value.gitlab_base_url),
    autoReview,
    trigger,
    updatedAt: coerceNumber(value.updated_at),
    updatedBy: typeof value.updated_by === 'string' ? value.updated_by : undefined
  };
};

const normalizeWebhookSyncResult = (
  value: unknown
): CodeReviewWebhookSyncResult | undefined => {
  if (!isRecord(value)) return undefined;
  const provider = normalizeProvider(value.provider);
  const repository =
    typeof value.repository === 'string' ? value.repository.trim() : '';
  if (!provider || !repository) return undefined;
  const mode =
    typeof value.mode === 'string' && value.mode.trim().toLowerCase() === 'auto'
      ? 'auto'
      : 'manual';

  const manualSetup = isRecord(value.manual_setup)
    ? {
        provider:
          normalizeProvider(value.manual_setup.provider) ?? provider,
        repository:
          typeof value.manual_setup.repository === 'string'
            ? value.manual_setup.repository
            : repository,
        events: Array.isArray(value.manual_setup.events)
          ? value.manual_setup.events.filter((item): item is string => typeof item === 'string')
          : undefined,
        payloadUrl:
          typeof value.manual_setup.payload_url === 'string'
            ? value.manual_setup.payload_url
            : undefined,
        secret:
          typeof value.manual_setup.secret === 'string'
            ? value.manual_setup.secret
            : undefined,
        hint:
          typeof value.manual_setup.hint === 'string'
            ? value.manual_setup.hint
            : undefined
      }
    : undefined;

  return {
    enabled: Boolean(value.enabled),
    ok: Boolean(value.ok),
    mode,
    message: typeof value.message === 'string' ? value.message : '',
    provider,
    repository,
    webhookUrl:
      typeof value.webhook_url === 'string' ? value.webhook_url : undefined,
    manualSetup
  };
};

export const fetchCodeReviewSettings = async (): Promise<{
  global: CodeReviewGlobalSettings;
  repositories: CodeReviewRepositorySetting[];
}> => {
  const { response } = await fetchFromCandidateEndpoints({
    type: 'settings',
    init: {
      method: 'GET',
      credentials: 'include'
    },
    skipStatusCodes: [404, 405]
  });
  if (!response.ok) {
    throw new CodeReviewRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, '查询代码审查设置失败');
  const globalRaw = isRecord(payload) && isRecord(payload.global) ? payload.global : {};
  const repositoriesRaw =
    isRecord(payload) && Array.isArray(payload.repositories)
      ? payload.repositories
      : [];

  return {
    global: {
      autoReviewEnabled: Boolean(globalRaw.auto_review_enabled),
      defaultTrigger: normalizeTrigger(globalRaw.default_trigger) ?? 'pr_open',
      updatedAt: coerceNumber(globalRaw.updated_at),
      updatedBy:
        typeof globalRaw.updated_by === 'string' ? globalRaw.updated_by : undefined
    },
    repositories: repositoriesRaw
      .map((item) => normalizeRepositorySetting(item))
      .filter((item): item is CodeReviewRepositorySetting => Boolean(item))
  };
};

export const updateCodeReviewGlobalSettings = async ({
  autoReviewEnabled,
  defaultTrigger
}: {
  autoReviewEnabled: boolean;
  defaultTrigger: CodeReviewTrigger;
}): Promise<CodeReviewGlobalSettings> => {
  const { response } = await fetchFromCandidateEndpoints({
    type: 'globalSettings',
    init: {
      method: 'PUT',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        auto_review_enabled: autoReviewEnabled,
        default_trigger: defaultTrigger
      })
    },
    skipStatusCodes: [404, 405]
  });
  if (!response.ok) {
    throw new CodeReviewRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, '保存代码审查全局设置失败');
  const globalRaw = isRecord(payload) && isRecord(payload.global) ? payload.global : {};
  return {
    autoReviewEnabled: Boolean(globalRaw.auto_review_enabled),
    defaultTrigger: normalizeTrigger(globalRaw.default_trigger) ?? 'pr_open',
    updatedAt: coerceNumber(globalRaw.updated_at),
    updatedBy: typeof globalRaw.updated_by === 'string' ? globalRaw.updated_by : undefined
  };
};

export const upsertCodeReviewRepositorySetting = async ({
  provider,
  repository,
  gitlabBaseUrl,
  autoReview,
  trigger
}: {
  provider: CodeReviewProvider;
  repository: string;
  gitlabBaseUrl?: string;
  autoReview: CodeReviewAutoReview;
  trigger: CodeReviewTrigger | 'follow_global';
}): Promise<{
  repositories: CodeReviewRepositorySetting[];
  webhookSync?: CodeReviewWebhookSyncResult;
}> => {
  const { response } = await fetchFromCandidateEndpoints({
    type: 'repoSettings',
    init: {
      method: 'PUT',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        provider,
        repository,
        gitlab_base_url: provider === 'gitlab' ? gitlabBaseUrl : undefined,
        auto_review: autoReview,
        trigger
      })
    },
    skipStatusCodes: [404, 405]
  });
  if (!response.ok) {
    throw new CodeReviewRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, '保存仓库代码审查设置失败');
  const repositoriesRaw =
    isRecord(payload) && Array.isArray(payload.repositories)
      ? payload.repositories
      : [];
  return {
    repositories: repositoriesRaw
      .map((item) => normalizeRepositorySetting(item))
      .filter((item): item is CodeReviewRepositorySetting => Boolean(item)),
    webhookSync:
      isRecord(payload) && payload.webhook_sync
        ? normalizeWebhookSyncResult(payload.webhook_sync)
        : undefined
  };
};

export const deleteCodeReviewRepositorySetting = async ({
  provider,
  repository,
  gitlabBaseUrl
}: {
  provider: CodeReviewProvider;
  repository: string;
  gitlabBaseUrl?: string;
}): Promise<{ deleted: boolean }> => {
  const params = new URLSearchParams();
  params.set('provider', provider);
  params.set('repository', repository);
  if (provider === 'gitlab' && gitlabBaseUrl) {
    params.set('gitlab_base_url', gitlabBaseUrl);
  }
  const { response } = await fetchFromCandidateEndpoints({
    type: 'repoSettings',
    params,
    init: {
      method: 'DELETE',
      credentials: 'include'
    },
    skipStatusCodes: [404, 405]
  });
  if (!response.ok) {
    throw new CodeReviewRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  assertPayloadOk(payload, '删除仓库代码审查设置失败');
  return {
    deleted: Boolean(isRecord(payload) && payload.deleted)
  };
};
