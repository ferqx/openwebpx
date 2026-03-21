import type { Thread, ThreadStatus } from '@langchain/langgraph-sdk';

export type TaskStatus = 'starting' | 'running' | 'completed' | 'stopped';

export type TaskItem = {
  id: string;
  title: string;
  repo: string;
  branch: string;
  dateLabel: string;
  updatedAt: string;
  createdAt?: string;
  status: TaskStatus;
  prompt: string;
};

export const statusLabel: Record<TaskStatus, string> = {
  completed: 'Completed',
  running: 'Running',
  starting: 'Starting container',
  stopped: 'Stopped'
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const getMetadataString = (thread: Thread, key: string) => {
  const metadata = thread.metadata;
  if (!isRecord(metadata)) return undefined;
  const value = metadata[key];
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
};

const formatDateLabel = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知日期';
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric'
  }).format(date);
};

const formatRelativeUpdatedAt = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '刚才';
  const diffMs = Date.now() - date.getTime();
  if (diffMs < 60_000) return '刚才';
  const diffMinutes = Math.floor(diffMs / 60_000);
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays} 天前`;
};

const mapThreadStatusToTaskStatus = (status: ThreadStatus): TaskStatus => {
  if (status === 'busy') return 'running';
  if (status === 'idle') return 'completed';
  return 'stopped';
};

export const mapThreadToTaskItem = (thread: Thread): TaskItem => {
  const title =
    getMetadataString(thread, 'name') ??
    `线程 ${thread.thread_id.slice(0, 8)}`;
  const prompt = getMetadataString(thread, 'prompt') ?? title;
  const repo = getMetadataString(thread, 'repo') ?? '未绑定仓库';
  const branch = getMetadataString(thread, 'branch') ?? 'main';

  return {
    id: thread.thread_id,
    title,
    repo,
    branch,
    dateLabel: formatDateLabel(thread.created_at),
    updatedAt: formatRelativeUpdatedAt(thread.updated_at),
    createdAt: thread.created_at,
    status: mapThreadStatusToTaskStatus(thread.status),
    prompt
  };
};

export const mapThreadsToTaskItems = (threads: Thread[]): TaskItem[] =>
  threads
    .map(mapThreadToTaskItem)
    .sort((a, b) => {
      const left = a.createdAt ? new Date(a.createdAt).getTime() : 0;
      const right = b.createdAt ? new Date(b.createdAt).getTime() : 0;
      return right - left;
    });
