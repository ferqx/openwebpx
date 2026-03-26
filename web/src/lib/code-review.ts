import { authFetch } from '@/lib/auth';
import {
  type CodeReviewFixRequest,
  type CodeReviewPublishRunResult,
  type CodeReviewRepositoryConfig,
  type CodeReviewRepositoryConfigUpdate,
  type CodeReviewRepositoryListResponse,
  type CodeReviewRepositorySyncRequest,
  type CodeReviewRepositorySummary,
  type CodeReviewRunDetail,
  type CodeReviewRunListResponse,
  type CodeReviewRunSummary
} from '@/business/portal/code-review-types';

export class CodeReviewRequestError extends Error {
  readonly status?: number;

  constructor(message: string, options?: { status?: number }) {
    super(message);
    this.name = 'CodeReviewRequestError';
    this.status = options?.status;
  }
}

const API_BASE = '/api/code-review';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const parseJsonSafely = async (response: Response) => {
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
};

const extractErrorMessage = (payload: unknown): string | undefined => {
  if (!isRecord(payload)) return undefined;
  const candidates = [payload.message, payload.detail, payload.error];
  const found = candidates.find((item) => typeof item === 'string');
  if (typeof found === 'string' && found.trim()) {
    return found.trim();
  }
  const nestedData = payload.data;
  if (isRecord(nestedData)) {
    return extractErrorMessage(nestedData);
  }
  return undefined;
};

const getErrorMessage = async (response: Response) => {
  const payload = await parseJsonSafely(response.clone());
  const payloadMessage = extractErrorMessage(payload);
  if (payloadMessage) return payloadMessage;
  const fallback = await response.text().catch(() => '');
  return fallback || `HTTP ${response.status}`;
};

const requestJson = async <TResponse>(
  path: string,
  init?: RequestInit
): Promise<TResponse> => {
  const response = await authFetch(path, init);
  if (!response.ok) {
    throw new CodeReviewRequestError(await getErrorMessage(response), {
      status: response.status
    });
  }
  const payload = await parseJsonSafely(response);
  return payload as TResponse;
};

const toJsonRequestInit = (
  init?: RequestInit,
  body?: Record<string, unknown>
) => {
  const headers = new Headers(init?.headers);
  if (body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return {
    ...init,
    headers,
    body: body === undefined ? init?.body : JSON.stringify(body)
  } satisfies RequestInit;
};

const toRepositoryList = (payload: unknown): CodeReviewRepositorySummary[] => {
  if (!isRecord(payload)) return [];
  const repositories = payload.repositories;
  if (!Array.isArray(repositories)) return [];
  return repositories.filter((item): item is CodeReviewRepositorySummary =>
    isRecord(item) &&
    typeof item.id === 'number' &&
    typeof item.provider === 'string' &&
    (item.provider === 'github' || item.provider === 'gitlab') &&
    typeof item.external_repo_id === 'string'
  );
};

const toRunList = (payload: unknown): CodeReviewRunSummary[] => {
  if (!isRecord(payload)) return [];
  const runs = payload.runs;
  if (!Array.isArray(runs)) return [];
  return runs.filter((item): item is CodeReviewRunSummary =>
    isRecord(item) &&
    typeof item.id === 'number' &&
    typeof item.repository_integration_id === 'number' &&
    typeof item.provider === 'string' &&
    (item.provider === 'github' || item.provider === 'gitlab') &&
    typeof item.event_type === 'string' &&
    typeof item.status === 'string' &&
    typeof item.idempotency_key === 'string' &&
    (item.thread_id === undefined || item.thread_id === null || typeof item.thread_id === 'string')
  );
};

export const listCodeReviewRepositories = async (): Promise<
  CodeReviewRepositorySummary[]
> => {
  const payload = await requestJson<CodeReviewRepositoryListResponse>(
    `${API_BASE}/repositories`,
    {
      method: 'GET',
      credentials: 'include'
    }
  );
  return toRepositoryList(payload);
};

export const syncCodeReviewRepositories = async (
  payload: CodeReviewRepositorySyncRequest
): Promise<CodeReviewRepositorySummary[]> => {
  const responsePayload = await requestJson<CodeReviewRepositoryListResponse>(
    `${API_BASE}/repositories/sync`,
    toJsonRequestInit(
      {
        method: 'POST',
        credentials: 'include'
      },
      payload
    )
  );
  return toRepositoryList(responsePayload);
};

export const getCodeReviewRepositoryConfig = async (
  repositoryId: number
): Promise<CodeReviewRepositoryConfig> => {
  const payload = await requestJson<CodeReviewRepositoryConfig>(
    `${API_BASE}/repositories/${encodeURIComponent(String(repositoryId))}/config`,
    {
      method: 'GET',
      credentials: 'include'
    }
  );
  return payload;
};

export const updateCodeReviewRepositoryConfig = async (
  repositoryId: number,
  payload: CodeReviewRepositoryConfigUpdate
): Promise<CodeReviewRepositoryConfig> => {
  return requestJson<CodeReviewRepositoryConfig>(
    `${API_BASE}/repositories/${encodeURIComponent(String(repositoryId))}/config`,
    toJsonRequestInit(
      {
        method: 'PUT',
        credentials: 'include'
      },
      payload
    )
  );
};

export const listCodeReviewRuns = async (): Promise<CodeReviewRunSummary[]> => {
  const payload = await requestJson<CodeReviewRunListResponse>(`${API_BASE}/runs`, {
    method: 'GET',
    credentials: 'include'
  });
  return toRunList(payload);
};

export const getCodeReviewRun = async (
  runId: number
): Promise<CodeReviewRunDetail> => {
  return requestJson<CodeReviewRunDetail>(
    `${API_BASE}/runs/${encodeURIComponent(String(runId))}`,
    {
      method: 'GET',
      credentials: 'include'
    }
  );
};

export const publishCodeReviewRun = async (
  runId: number
): Promise<CodeReviewPublishRunResult> => {
  return requestJson<CodeReviewPublishRunResult>(
    `${API_BASE}/runs/${encodeURIComponent(String(runId))}/publish`,
    {
      method: 'POST',
      credentials: 'include'
    }
  );
};

export const approveCodeReviewFixRequest = async (
  fixRequestId: number
): Promise<CodeReviewFixRequest> => {
  return requestJson<CodeReviewFixRequest>(
    `${API_BASE}/fix-requests/${encodeURIComponent(String(fixRequestId))}/approve`,
    {
      method: 'POST',
      credentials: 'include'
    }
  );
};

export const rejectCodeReviewFixRequest = async (
  fixRequestId: number,
  reason?: string
): Promise<CodeReviewFixRequest> => {
  return requestJson<CodeReviewFixRequest>(
    `${API_BASE}/fix-requests/${encodeURIComponent(String(fixRequestId))}/reject`,
    toJsonRequestInit(
      {
        method: 'POST',
        credentials: 'include'
      },
      { reason: reason ?? null }
    )
  );
};
