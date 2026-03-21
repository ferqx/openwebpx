import { authFetch } from "@/lib/auth";

export type SandboxInitializeStepStatus =
  | "pending"
  | "running"
  | "success"
  | "error"
  | "skipped";

export type SandboxInitializeStep = {
  key: string;
  title: string;
  status: SandboxInitializeStepStatus;
  detail?: string;
};

export type SandboxInitializeResult = {
  thread_id: string;
  graph_id: string;
  status: "ok" | "error";
  success: boolean;
  error?: string;
  steps: SandboxInitializeStep[];
  container_id?: string;
  service_status?: Record<string, unknown>;
  runtime_timestamp?: string;
};

export type SandboxBootstrapStatus = "idle" | "running" | "success" | "error";

export type SandboxBootstrapLog = {
  timestamp?: string | null;
  level?: string;
  step?: string;
  message: string;
};

export type SandboxBootstrapResult = {
  thread_id: string;
  graph_id: string;
  status: SandboxBootstrapStatus;
  accepted?: boolean;
  request_id?: string;
  run_id?: string;
  run_status?: string;
  error?: string | null;
  steps: SandboxInitializeStep[];
  logs: SandboxBootstrapLog[];
  event_seq?: number;
  started_at?: string | null;
  updated_at?: string | null;
  finished_at?: string | null;
  reset_success?: boolean;
  reset_error?: string | null;
  destroy_container?: boolean;
  destroyed_container_id?: string | null;
};

export type SandboxThreadCancelAction = "cancel" | "interrupt";

export type SandboxThreadCancelResult = {
  thread_id: string;
  graph_id: string;
  action: SandboxThreadCancelAction;
  cancelled_run_ids: string[];
  cancelled_run_count: number;
  cancel_signal_failures: string[];
  bootstrap_task_cancelled: boolean;
  thread_status?: string;
  updated_at?: string;
};

export type SandboxBootstrapEvent = {
  seq: number;
  type: "log";
  timestamp?: string | null;
  level?: string;
  step?: string;
  message: string;
};

export type SandboxBootstrapStreamEvent =
  | {
      type: "bootstrap_event";
      data: SandboxBootstrapEvent;
    }
  | {
      type: "bootstrap_snapshot";
      data: SandboxBootstrapResult;
    }
  | {
      type: "bootstrap_done";
      data: {
        thread_id: string;
        status: SandboxBootstrapStatus;
        event_seq: number;
      };
    }
  | {
      type: "bootstrap_error";
      data: {
        thread_id?: string;
        error?: string;
        message?: string;
      };
    };

export type SandboxGitFileEntry = {
  status: string;
  index_status: string;
  worktree_status: string;
  path: string;
  old_path?: string | null;
  is_staged: boolean;
  is_unstaged: boolean;
};

export type SandboxThreadGitChangesResult = {
  thread_id: string;
  graph_id: string;
  files: SandboxGitFileEntry[];
  count: number;
  untracked_files?: string[];
  diff?: string | null;
  diff_truncated?: boolean;
  pending_initialization?: boolean;
  timestamp?: string;
};

export type SandboxThreadGitCommitResult = {
  thread_id: string;
  graph_id: string;
  commit_id: string;
  commit_message: string;
  message_source: "user" | "model";
  staged_count_before_commit: number;
  staged_count_after_commit: number;
  unstaged_count_after_commit: number;
  commit_output?: string;
  commit_output_truncated?: boolean;
  timestamp?: string;
};

const parseJsonSafely = async (response: Response) => {
  try {
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
};

const getErrorMessage = async (response: Response) => {
  const payload = await parseJsonSafely(response);
  if (payload && typeof payload === "object") {
    const message = (payload as { detail?: unknown; error?: unknown }).detail;
    if (typeof message === "string" && message.trim()) return message.trim();
    const fallback = (payload as { error?: unknown }).error;
    if (typeof fallback === "string" && fallback.trim()) return fallback.trim();
  }
  const text = await response.text().catch(() => "");
  return text || `HTTP ${response.status}`;
};

export const initializeSandboxThreadEnvironment = async (
  threadId: string,
): Promise<SandboxInitializeResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/initialize`;
  const response = await authFetch(requestUrl, {
    method: "POST",
  });

  if (!response.ok) {
    const message = await getErrorMessage(response);
    throw new Error(message);
  }

  const payload = (await response.json()) as SandboxInitializeResult;
  return {
    ...payload,
    steps: Array.isArray(payload.steps) ? payload.steps : [],
  };
};

const normalizeBootstrapResult = (
  payload: SandboxBootstrapResult,
): SandboxBootstrapResult => {
  const steps = Array.isArray(payload.steps) ? payload.steps : [];
  const logs = Array.isArray(payload.logs)
    ? payload.logs.filter(
        (log): log is SandboxBootstrapLog =>
          typeof log === "object" &&
          log !== null &&
          typeof (log as { message?: unknown }).message === "string",
      )
    : [];
  return {
    ...payload,
    steps,
    logs,
    event_seq:
      typeof payload.event_seq === "number" && payload.event_seq >= 0
        ? payload.event_seq
        : 0,
  };
};

type StartSandboxBootstrapPayload = {
  message: string;
  force?: boolean;
  stream_mode?: string | string[];
};

export const startSandboxThreadBootstrap = async (
  threadId: string,
  payload: StartSandboxBootstrapPayload,
): Promise<SandboxBootstrapResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }
  const message = payload.message.trim();
  if (!message) {
    throw new Error("message is required");
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/bootstrap`;
  const response = await authFetch(requestUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message,
      force: Boolean(payload.force),
      stream_mode: payload.stream_mode,
    }),
  });

  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    throw new Error(messageText);
  }

  const result = (await response.json()) as SandboxBootstrapResult;
  return normalizeBootstrapResult(result);
};

export const getSandboxThreadBootstrapStatus = async (
  threadId: string,
): Promise<SandboxBootstrapResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/bootstrap`;
  const response = await authFetch(requestUrl, {
    method: "GET",
  });

  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    throw new Error(messageText);
  }

  const result = (await response.json()) as SandboxBootstrapResult;
  return normalizeBootstrapResult(result);
};

type ResetSandboxBootstrapPayload = {
  destroy_container?: boolean;
};

export const resetSandboxThreadBootstrap = async (
  threadId: string,
  payload?: ResetSandboxBootstrapPayload,
): Promise<SandboxBootstrapResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/bootstrap/reset`;
  const response = await authFetch(requestUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      destroy_container: payload?.destroy_container ?? true,
    }),
  });

  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    throw new Error(messageText);
  }

  const result = (await response.json()) as SandboxBootstrapResult;
  return normalizeBootstrapResult(result);
};

export const cancelSandboxThreadRuns = async (
  threadId: string,
  action: SandboxThreadCancelAction = "interrupt",
): Promise<SandboxThreadCancelResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/cancel?action=${encodeURIComponent(action)}`;
  const response = await authFetch(requestUrl, {
    method: "POST",
  });

  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    const requestError = new Error(messageText) as Error & { status?: number };
    requestError.status = response.status;
    throw requestError;
  }

  const result = (await response.json()) as SandboxThreadCancelResult;
  return {
    ...result,
    cancelled_run_ids: Array.isArray(result.cancelled_run_ids)
      ? result.cancelled_run_ids
      : [],
    cancel_signal_failures: Array.isArray(result.cancel_signal_failures)
      ? result.cancel_signal_failures
      : [],
    cancelled_run_count:
      typeof result.cancelled_run_count === "number" &&
      Number.isFinite(result.cancelled_run_count)
        ? result.cancelled_run_count
        : 0,
    bootstrap_task_cancelled: Boolean(result.bootstrap_task_cancelled),
  };
};

const parseSseEventChunk = (chunk: string) => {
  const lines = chunk.split(/\r?\n/);
  let eventName = "message";
  const dataLines: string[] = [];

  lines.forEach((line) => {
    if (!line) return;
    if (line.startsWith(":")) return;
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim() || "message";
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  });

  if (dataLines.length === 0) return null;
  const dataText = dataLines.join("\n");
  let data: unknown = null;
  try {
    data = JSON.parse(dataText) as unknown;
  } catch {
    data = null;
  }
  return { eventName, data };
};

type StreamSandboxBootstrapOptions = {
  fromSeq?: number;
  signal?: AbortSignal;
  onEvent: (event: SandboxBootstrapStreamEvent) => void;
};

export const streamSandboxThreadBootstrap = async (
  threadId: string,
  options: StreamSandboxBootstrapOptions,
): Promise<void> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const fromSeq = Math.max(0, options.fromSeq ?? 0);
  const query = new URLSearchParams();
  if (fromSeq > 0) {
    query.set("from_seq", String(fromSeq));
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/bootstrap/stream${
    query.size > 0 ? `?${query.toString()}` : ""
  }`;
  const response = await authFetch(requestUrl, {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
    },
    signal: options.signal,
  });

  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    throw new Error(messageText);
  }

  if (!response.body) {
    throw new Error("Bootstrap stream response body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    let separatorIndex = buffer.indexOf("\n\n");

    while (separatorIndex >= 0) {
      const chunk = buffer.slice(0, separatorIndex).trim();
      buffer = buffer.slice(separatorIndex + 2);
      if (chunk) {
        const parsed = parseSseEventChunk(chunk);
        if (parsed) {
          const { eventName, data } = parsed;
          if (
            eventName === "bootstrap_snapshot" &&
            data &&
            typeof data === "object"
          ) {
            options.onEvent({
              type: "bootstrap_snapshot",
              data: normalizeBootstrapResult(data as SandboxBootstrapResult),
            });
          } else if (
            eventName === "bootstrap_event" &&
            data &&
            typeof data === "object"
          ) {
            options.onEvent({
              type: "bootstrap_event",
              data: data as SandboxBootstrapEvent,
            });
          } else if (
            eventName === "bootstrap_done" &&
            data &&
            typeof data === "object"
          ) {
            options.onEvent({
              type: "bootstrap_done",
              data: data as {
                thread_id: string;
                status: SandboxBootstrapStatus;
                event_seq: number;
              },
            });
          } else if (
            eventName === "bootstrap_error" &&
            data &&
            typeof data === "object"
          ) {
            options.onEvent({
              type: "bootstrap_error",
              data: data as {
                thread_id?: string;
                error?: string;
                message?: string;
              },
            });
          }
        }
      }
      separatorIndex = buffer.indexOf("\n\n");
    }
  }
};

type FetchSandboxThreadGitChangesOptions = {
  includeDiff?: boolean;
  diffMaxChars?: number;
};

const normalizeSandboxGitFileEntry = (
  value: unknown,
): SandboxGitFileEntry | null => {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const path = typeof record.path === "string" ? record.path.trim() : "";
  if (!path) return null;
  return {
    status: typeof record.status === "string" ? record.status : "",
    index_status:
      typeof record.index_status === "string" ? record.index_status : " ",
    worktree_status:
      typeof record.worktree_status === "string" ? record.worktree_status : " ",
    path,
    old_path: typeof record.old_path === "string" ? record.old_path : null,
    is_staged: Boolean(record.is_staged),
    is_unstaged: Boolean(record.is_unstaged),
  };
};

const normalizeSandboxThreadGitChangesResult = (
  payload: unknown,
): SandboxThreadGitChangesResult => {
  const record =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : {};
  const filesRaw = Array.isArray(record.files) ? record.files : [];
  const files = filesRaw
    .map((item) => normalizeSandboxGitFileEntry(item))
    .filter((item): item is SandboxGitFileEntry => item !== null);
  return {
    thread_id: typeof record.thread_id === "string" ? record.thread_id : "",
    graph_id: typeof record.graph_id === "string" ? record.graph_id : "",
    files,
    count:
      typeof record.count === "number" && Number.isFinite(record.count)
        ? record.count
        : files.length,
    untracked_files: Array.isArray(record.untracked_files)
      ? record.untracked_files.filter(
          (item): item is string => typeof item === "string" && item.trim().length > 0,
        )
      : [],
    diff: typeof record.diff === "string" ? record.diff : null,
    diff_truncated: Boolean(record.diff_truncated),
    pending_initialization: Boolean(record.pending_initialization),
    timestamp: typeof record.timestamp === "string" ? record.timestamp : undefined,
  };
};

const fetchSandboxThreadGitChanges = async (
  threadId: string,
  path: "staged" | "unstaged",
  options?: FetchSandboxThreadGitChangesOptions,
): Promise<SandboxThreadGitChangesResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const query = new URLSearchParams();
  if (typeof options?.includeDiff === "boolean") {
    query.set("include_diff", String(options.includeDiff));
  }
  if (
    typeof options?.diffMaxChars === "number" &&
    Number.isFinite(options.diffMaxChars) &&
    options.diffMaxChars >= 0
  ) {
    query.set("diff_max_chars", String(Math.floor(options.diffMaxChars)));
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/git/${path}${
    query.size > 0 ? `?${query.toString()}` : ""
  }`;
  const response = await authFetch(requestUrl, { method: "GET" });
  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    throw new Error(messageText);
  }

  const payload = (await response.json()) as unknown;
  return normalizeSandboxThreadGitChangesResult(payload);
};

export const fetchSandboxThreadGitUnstaged = async (
  threadId: string,
  options?: FetchSandboxThreadGitChangesOptions,
): Promise<SandboxThreadGitChangesResult> =>
  fetchSandboxThreadGitChanges(threadId, "unstaged", options);

export const fetchSandboxThreadGitStaged = async (
  threadId: string,
  options?: FetchSandboxThreadGitChangesOptions,
): Promise<SandboxThreadGitChangesResult> =>
  fetchSandboxThreadGitChanges(threadId, "staged", options);

type CommitSandboxThreadGitChangesPayload = {
  message?: string;
  generate_message?: boolean;
};

export const commitSandboxThreadGitChanges = async (
  threadId: string,
  payload: CommitSandboxThreadGitChangesPayload,
): Promise<SandboxThreadGitCommitResult> => {
  const trimmedThreadId = threadId.trim();
  if (!trimmedThreadId) {
    throw new Error("threadId is required");
  }

  const requestUrl = `/api/sandbox/threads/${encodeURIComponent(trimmedThreadId)}/git/commit`;
  const response = await authFetch(requestUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message:
        typeof payload.message === "string" && payload.message.trim()
          ? payload.message.trim()
          : undefined,
      generate_message: Boolean(payload.generate_message),
    }),
  });

  if (!response.ok) {
    const messageText = await getErrorMessage(response);
    throw new Error(messageText);
  }

  const result = (await response.json()) as SandboxThreadGitCommitResult;
  return {
    ...result,
    commit_id: typeof result.commit_id === "string" ? result.commit_id : "",
    commit_message:
      typeof result.commit_message === "string" ? result.commit_message : "",
    message_source: result.message_source === "model" ? "model" : "user",
    staged_count_before_commit:
      typeof result.staged_count_before_commit === "number" &&
      Number.isFinite(result.staged_count_before_commit)
        ? result.staged_count_before_commit
        : 0,
    staged_count_after_commit:
      typeof result.staged_count_after_commit === "number" &&
      Number.isFinite(result.staged_count_after_commit)
        ? result.staged_count_after_commit
        : 0,
    unstaged_count_after_commit:
      typeof result.unstaged_count_after_commit === "number" &&
      Number.isFinite(result.unstaged_count_after_commit)
        ? result.unstaged_count_after_commit
        : 0,
    commit_output:
      typeof result.commit_output === "string" ? result.commit_output : "",
    commit_output_truncated: Boolean(result.commit_output_truncated),
  };
};
