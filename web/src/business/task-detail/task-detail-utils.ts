import type { Thread as LangGraphThread } from '@langchain/langgraph-sdk';

export type ThreadReviewCommentPublishStatus = {
  status: string;
  reason?: string;
  provider?: string;
  summary?: string;
  extractedCount?: number;
  filteredCount?: number;
  publishedCount?: number;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

export const getErrorStatusCode = (error: unknown) => {
  if (!error || typeof error !== 'object') return undefined;
  const record = error as Record<string, unknown>;
  const directStatus = record.status;
  if (typeof directStatus === 'number') return directStatus;
  if (typeof directStatus === 'string') {
    const parsed = Number.parseInt(directStatus, 10);
    if (Number.isFinite(parsed)) return parsed;
  }

  const statusCode = record.statusCode;
  if (typeof statusCode === 'number') return statusCode;
  if (typeof statusCode === 'string') {
    const parsed = Number.parseInt(statusCode, 10);
    if (Number.isFinite(parsed)) return parsed;
  }

  const response = record.response;
  if (response && typeof response === 'object') {
    const responseStatus = (response as Record<string, unknown>).status;
    if (typeof responseStatus === 'number') return responseStatus;
    if (typeof responseStatus === 'string') {
      const parsed = Number.parseInt(responseStatus, 10);
      if (Number.isFinite(parsed)) return parsed;
    }
  }

  return undefined;
};

export const getErrorMessage = (error: unknown) => {
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  if (!error || typeof error !== 'object') return '未知错误';
  const record = error as Record<string, unknown>;
  if (typeof record.message === 'string' && record.message.trim()) {
    return record.message;
  }
  return '请求失败，请稍后重试';
};

export const getThreadNameFromMetadata = (thread?: LangGraphThread) => {
  const metadata = thread?.metadata;
  if (!isRecord(metadata)) return undefined;
  const name = metadata.name;
  if (typeof name !== 'string') return undefined;
  const trimmed = name.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

export const getThreadReviewCommentPublishStatus = (
  thread?: LangGraphThread
): ThreadReviewCommentPublishStatus | undefined => {
  const metadata = thread?.metadata;
  if (!isRecord(metadata)) return undefined;
  const raw = metadata.review_comment_publish;
  if (!isRecord(raw)) return undefined;

  const status =
    typeof raw.status === 'string' && raw.status.trim()
      ? raw.status.trim()
      : undefined;
  if (!status) return undefined;

  const parseOptionalNumber = (value: unknown) =>
    typeof value === 'number' && Number.isFinite(value) ? value : undefined;

  return {
    status,
    reason: typeof raw.reason === 'string' ? raw.reason : undefined,
    provider: typeof raw.provider === 'string' ? raw.provider : undefined,
    summary: typeof raw.summary === 'string' ? raw.summary : undefined,
    extractedCount: parseOptionalNumber(raw.extracted_count),
    filteredCount: parseOptionalNumber(raw.filtered_count),
    publishedCount: parseOptionalNumber(raw.published_count)
  };
};

export const formatThreadCreatedAt = (value?: string) => {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date);
};

const buildMessageContentDigest = (content: unknown) => {
  if (typeof content === 'string') {
    const tail = content.slice(-24);
    return `s:${content.length}:${tail}`;
  }
  if (Array.isArray(content)) {
    const normalized = content
      .map((item) => {
        if (!item || typeof item !== 'object') return typeof item;
        const record = item as Record<string, unknown>;
        const type = typeof record.type === 'string' ? record.type : 'unknown';
        const text =
          typeof record.text === 'string'
            ? `${record.text.length}:${record.text.slice(-12)}`
            : '';
        return `${type}:${text}`;
      })
      .join('|');
    return `a:${content.length}:${normalized}`;
  }
  if (content == null) return 'n';
  return `o:${typeof content}`;
};

export const buildMessagesDigest = (
  value: Array<{
    id?: string;
    type: string;
    content?: unknown;
    tool_call_id?: string;
    status?: unknown;
  }>
) =>
  value
    .map((message, index) => {
      const id = message.id?.trim() || `${message.type}-${index}`;
      const toolCallId = message.tool_call_id?.trim() ?? '';
      const status = typeof message.status === 'string' ? message.status : '';
      const contentDigest = buildMessageContentDigest(message.content);
      return `${id}#${message.type}#${toolCallId}#${status}#${contentDigest}`;
    })
    .join('||');

export const INITIAL_MESSAGES_MAX_WAIT_MS = 1200;

export type UnifiedDiffStats = {
  added: number;
  removed: number;
};

export const getUnifiedDiffStats = (diff?: string | null): UnifiedDiffStats => {
  if (!diff) {
    return { added: 0, removed: 0 };
  }

  let added = 0;
  let removed = 0;
  diff.split('\n').forEach((line) => {
    if (!line) return;
    if (line.startsWith('+++') || line.startsWith('---')) return;
    if (line.startsWith('+')) {
      added += 1;
      return;
    }
    if (line.startsWith('-')) {
      removed += 1;
    }
  });

  return { added, removed };
};
