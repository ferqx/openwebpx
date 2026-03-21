import { type Message as LangGraphMessage } from "@langchain/langgraph-sdk";
import {
  type ThreadChatDisplayMessage,
  type ThreadChatPart,
  type ThreadChatTokenUsageSummary,
} from "@/business/thread-chat/types";
import {
  type SandboxBootstrapLog,
  type SandboxBootstrapResult,
  type SandboxBootstrapStatus,
  type SandboxInitializeStep,
} from "@/lib/sandbox";
import {
  getApplyPatchChangeCount,
  getApplyPatchContent,
  getApplyPatchDiffValues,
  getApplyPatchFilePaths,
} from "@/hooks/thread-chat-diff-utils";

type ToolCallRecord = {
  id: string;
  args?: unknown;
};

type AiToolCallRecord = ToolCallRecord & {
  name?: unknown;
};

type ToolDiffHunk = NonNullable<
  Extract<ThreadChatPart, { type: "tool" }>["diffHunks"]
>[number];

type ToolFileDiffMetadata = {
  toolName?: string;
  filePath?: string;
  beforeLineCount?: number;
  afterLineCount?: number;
  deltaAdded?: number;
  deltaRemoved?: number;
  netAdded?: number;
  netRemoved?: number;
  fileVersion?: number;
  netPartial?: boolean;
  hunks: ToolDiffHunk[];
};

type ToolDiffSection = NonNullable<
  Extract<ThreadChatPart, { type: "tool" }>["diffSections"]
>[number];

type ThreadChatTextPart = Extract<
  ThreadChatPart,
  { type: "reasoning" | "content" }
>;

type CachedNormalizedMessage = {
  signature: string;
  message: ThreadChatDisplayMessage;
};

export type EnvironmentInitDisplay = {
  id: string;
  status: "running" | "success" | "error";
  title?: string;
  steps: SandboxInitializeStep[];
  logs: SandboxBootstrapLog[];
  error?: string;
  runId?: string;
  runStatus?: string;
};

const DEFAULT_ENV_INIT_STEPS: SandboxInitializeStep[] = [
  { key: "container", title: "容器创建", status: "pending" },
  { key: "repo", title: "拉取代码", status: "pending" },
  { key: "bootstrap", title: "下载依赖并启动", status: "pending" },
];

const ENV_INIT_STATUS_TEXT: Record<SandboxInitializeStep["status"], string> = {
  pending: "等待中",
  running: "进行中",
  success: "完成",
  error: "失败",
  skipped: "跳过",
};

const ENV_LOG_LEVEL_TEXT: Record<string, string> = {
  info: "INFO",
  error: "ERROR",
  warning: "WARN",
  debug: "DEBUG",
};

const TOOL_CALL_FALLBACK_PREFIX = "__tool_msg__:";
const normalizedMessageCache = new WeakMap<
  LangGraphMessage,
  CachedNormalizedMessage
>();
const stabilizedMessagesStore = new Map<string, ThreadChatDisplayMessage[]>();

const getBootstrapOptimisticUserStorageKey = (threadId: string) =>
  `thread:bootstrap-optimistic-user:${threadId}`;

export const readBootstrapOptimisticUserText = (threadId: string) => {
  if (typeof window === "undefined") return "";
  const normalizedThreadId = threadId.trim();
  if (!normalizedThreadId) return "";
  const value = window.sessionStorage.getItem(
    getBootstrapOptimisticUserStorageKey(normalizedThreadId),
  );
  return value?.trim() ?? "";
};

export const writeBootstrapOptimisticUserText = (
  threadId: string,
  text: string,
) => {
  if (typeof window === "undefined") return;
  const normalizedThreadId = threadId.trim();
  if (!normalizedThreadId) return;
  const normalizedText = text.trim();
  const storageKey = getBootstrapOptimisticUserStorageKey(normalizedThreadId);
  if (!normalizedText) {
    window.sessionStorage.removeItem(storageKey);
    return;
  }
  window.sessionStorage.setItem(storageKey, normalizedText);
};

const isTextContentItem = (
  item: unknown,
): item is { type: "text"; text: string } =>
  typeof item === "object" &&
  item !== null &&
  "type" in item &&
  "text" in item &&
  (item as { type?: unknown }).type === "text" &&
  typeof (item as { text?: unknown }).text === "string";

const safeStringify = (value: unknown) => {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const messageContentToText = (content: LangGraphMessage["content"]) => {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const textContent = content
      .filter(isTextContentItem)
      .map((item) => item.text)
      .join("\n");
    if (textContent) return textContent;
    return safeStringify(content);
  }
  if (content == null) return "";
  return safeStringify(content);
};

const isToolCallRecord = (value: unknown): value is ToolCallRecord => {
  if (typeof value !== "object" || value === null) return false;
  if (!("id" in value)) return false;
  return typeof (value as { id?: unknown }).id === "string";
};

const isAiToolCallRecord = (value: unknown): value is AiToolCallRecord =>
  isToolCallRecord(value);

const getAiToolCalls = (message: LangGraphMessage): AiToolCallRecord[] => {
  if (message.type !== "ai") return [];
  const rawToolCalls = (message as { tool_calls?: unknown }).tool_calls;
  if (!Array.isArray(rawToolCalls)) return [];
  return rawToolCalls.filter(isAiToolCallRecord);
};

const getToolCallArgsFromPreviousAiMessage = (
  messages: LangGraphMessage[],
  index: number,
  toolCallId: string,
) => {
  if (index <= 0 || !toolCallId.trim()) return undefined;

  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const previousMessage = messages[cursor];
    if (!previousMessage || previousMessage.type !== "ai") continue;

    const rawToolCalls = (previousMessage as { tool_calls?: unknown }).tool_calls;
    if (!Array.isArray(rawToolCalls)) continue;

    const matchedToolCall = rawToolCalls
      .filter(isToolCallRecord)
      .find((toolCall) => toolCall.id === toolCallId);
    if (matchedToolCall) return matchedToolCall.args;
  }

  return undefined;
};

const extractStructuredShellOutput = (toolMessageContent: string) => {
  const normalizedContent = toolMessageContent.replace(/\r\n/g, "\n");
  const lines = normalizedContent.split("\n");
  const outputLines: string[] = [];
  let hasExitCode = false;
  let hasTruncated = false;
  let hasOutput = false;
  let readingOutput = false;

  lines.forEach((line) => {
    if (/^Exit code:\s*/i.test(line) || /^Truncated:\s*/i.test(line)) {
      if (readingOutput) {
        readingOutput = false;
      }
      if (/^Exit code:\s*/i.test(line)) hasExitCode = true;
      if (/^Truncated:\s*/i.test(line)) hasTruncated = true;
      return;
    }

    const outputMatch = line.match(/^Output:\s*(.*)$/i);
    if (outputMatch) {
      hasOutput = true;
      readingOutput = true;
      const inlineOutput = outputMatch[1] ?? "";
      if (inlineOutput.length > 0) {
        outputLines.push(inlineOutput);
      }
      return;
    }

    if (readingOutput) {
      outputLines.push(line);
    }
  });

  if (!hasExitCode || !hasTruncated || !hasOutput) {
    return undefined;
  }
  return outputLines.join("\n").trimEnd();
};

const resolveToolDisplayContent = (
  toolName: string,
  toolMessageContent: string,
  toolCallArgs: unknown,
  toolInvocation?: string,
  deferHeavyPayload = false,
) => {
  if (deferHeavyPayload) return "";
  if (toolName === "ls" || toolName === "execute") {
    return extractStructuredShellOutput(toolMessageContent) ?? toolMessageContent;
  }
  if (toolName === "write_file") {
    const newString =
      typeof toolCallArgs === "object" &&
      toolCallArgs !== null &&
      "content" in toolCallArgs &&
      typeof (toolCallArgs as { content?: unknown }).content === "string"
        ? (toolCallArgs as { content: string }).content
        : "";
    const newLines = newString.split("\n");
    const newDiff = newLines.map((line) => `+${line}`).join("\n");
    const fileHeader = toolInvocation?.trim()
      ? `--- /dev/null\n+++ b/${toolInvocation.trim()}\n`
      : "";
    const body = newDiff.trim() || "+";
    return `${fileHeader}@@\n${body}`.trim();
  }
  if (toolName === "edit_file") {
    const oldString =
      typeof toolCallArgs === "object" &&
      toolCallArgs !== null &&
      "old_string" in toolCallArgs &&
      typeof (toolCallArgs as { old_string?: unknown }).old_string === "string"
        ? (toolCallArgs as { old_string: string }).old_string
        : "";
    const newString =
      typeof toolCallArgs === "object" &&
      toolCallArgs !== null &&
      "new_string" in toolCallArgs &&
      typeof (toolCallArgs as { new_string?: unknown }).new_string === "string"
        ? (toolCallArgs as { new_string: string }).new_string
        : "";

    const oldLines = oldString.split("\n");
    const newLines = newString.split("\n");
    const oldDiff = oldLines.map((line) => `-${line}`).join("\n");
    const newDiff = newLines.map((line) => `+${line}`).join("\n");
    const fileHeader = toolInvocation?.trim()
      ? `--- a/${toolInvocation.trim()}\n+++ b/${toolInvocation.trim()}\n`
      : "";
    const body = `${oldDiff}\n${newDiff}`.trim();
    return `${fileHeader}@@\n${body}`.trim();
  }
  if (toolName === "apply_patch") {
    const patchContent = getApplyPatchContent(toolCallArgs).trim();
    if (patchContent) return patchContent;
  }
  if (toolCallArgs == null) return toolMessageContent;

  const filePath =
    typeof toolCallArgs === "object" &&
    toolCallArgs !== null &&
    "file_path" in toolCallArgs &&
    typeof (toolCallArgs as { file_path?: unknown }).file_path === "string"
      ? (toolCallArgs as { file_path: string }).file_path.trim()
      : "";

  if (
    typeof toolCallArgs === "object" &&
    toolCallArgs !== null &&
    "content" in toolCallArgs &&
    typeof (toolCallArgs as { content?: unknown }).content === "string"
  ) {
    const argsContent = (toolCallArgs as { content: string }).content.trim();
    if (argsContent) {
      return filePath ? `# ${filePath}\n${argsContent}` : argsContent;
    }
  }

  if (filePath) return `# ${filePath}`;

  return safeStringify(toolCallArgs);
};

const getToolInvocation = (toolName: string, toolCallArgs: unknown) => {
  if (toolCallArgs == null || typeof toolCallArgs !== "object") return "";

  const args = toolCallArgs as {
    file_path?: unknown;
    path?: unknown;
    command?: unknown;
    cmd?: unknown;
    shell?: unknown;
  };

  const filePath =
    typeof args.file_path === "string" ? args.file_path.trim() : "";
  const path = typeof args.path === "string" ? args.path.trim() : "";
  const command =
    typeof args.command === "string"
      ? args.command.trim()
      : typeof args.cmd === "string"
        ? args.cmd.trim()
        : typeof args.shell === "string"
          ? args.shell.trim()
          : "";

  if (toolName === "execute") return command || path || filePath;
  if (toolName === "ls" || toolName === "read_file") {
    return path || filePath || command;
  }
  if (toolName === "write_file" || toolName === "edit_file") {
    return filePath || path || command;
  }
  if (toolName === "apply_patch") {
    const patchContent = getApplyPatchContent(toolCallArgs);
    if (patchContent) {
      const paths = getApplyPatchFilePaths(patchContent);
      if (paths.length > 0) return paths.join(", ");
    }
    return filePath || path || command;
  }

  return filePath || path || command;
};

const getLineCount = (value: string) => {
  if (!value) return 0;
  return value.split("\n").length;
};

const getToolChangeCount = (
  toolName: string,
  toolCallArgs: unknown,
  deferHeavyPayload = false,
) => {
  if (
    toolName !== "edit_file" &&
    toolName !== "write_file" &&
    toolName !== "apply_patch"
  ) {
    return { added: 0, removed: 0 };
  }
  if (deferHeavyPayload) {
    return { added: 0, removed: 0 };
  }
  if (toolCallArgs == null || typeof toolCallArgs !== "object") {
    return { added: 0, removed: 0 };
  }

  const args = toolCallArgs as {
    new_string?: unknown;
    old_string?: unknown;
    content?: unknown;
    patch_content?: unknown;
  };
  if (toolName === "apply_patch") {
    const patchContent =
      typeof args.patch_content === "string" ? args.patch_content : "";
    return getApplyPatchChangeCount(patchContent);
  }
  if (toolName === "write_file") {
    return {
      added: typeof args.content === "string" ? getLineCount(args.content) : 0,
      removed: 0,
    };
  }

  return {
    added:
      typeof args.new_string === "string" ? getLineCount(args.new_string) : 0,
    removed:
      typeof args.old_string === "string" ? getLineCount(args.old_string) : 0,
  };
};

const getToolDiffValues = (
  toolName: string,
  toolCallArgs: unknown,
  deferHeavyPayload = false,
) => {
  if (
    deferHeavyPayload &&
    (toolName === "write_file" ||
      toolName === "edit_file" ||
      toolName === "apply_patch")
  ) {
    return { oldValue: "", newValue: "" };
  }
  if (toolCallArgs == null || typeof toolCallArgs !== "object") {
    return { oldValue: "", newValue: "" };
  }

  const args = toolCallArgs as {
    old_string?: unknown;
    new_string?: unknown;
    content?: unknown;
    patch_content?: unknown;
  };

  if (toolName === "write_file") {
    return {
      oldValue: "",
      newValue: typeof args.content === "string" ? args.content : "",
    };
  }

  if (toolName === "edit_file") {
    return {
      oldValue: typeof args.old_string === "string" ? args.old_string : "",
      newValue: typeof args.new_string === "string" ? args.new_string : "",
    };
  }

  if (toolName === "apply_patch") {
    const patchContent =
      typeof args.patch_content === "string" ? args.patch_content : "";
    return getApplyPatchDiffValues(patchContent);
  }

  return { oldValue: "", newValue: "" };
};

const isDiffToolName = (toolName: string) =>
  toolName === "write_file" ||
  toolName === "edit_file" ||
  toolName === "apply_patch";

const getPositiveIntFromUnknown = (value: unknown) => {
  if (typeof value === "number" && Number.isInteger(value) && value > 0) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isInteger(parsed) && parsed > 0) return parsed;
  }
  return undefined;
};

const getNonNegativeIntFromUnknown = (value: unknown) => {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isInteger(parsed) && parsed >= 0) return parsed;
  }
  return undefined;
};

const parseToolDiffHunk = (value: unknown): ToolDiffHunk | undefined => {
  if (typeof value !== "object" || value == null) return undefined;
  const record = value as Record<string, unknown>;
  const oldStart = getNonNegativeIntFromUnknown(
    record.old_start ?? record.oldStart,
  );
  const oldCount = getNonNegativeIntFromUnknown(
    record.old_count ?? record.oldCount,
  );
  const newStart = getNonNegativeIntFromUnknown(
    record.new_start ?? record.newStart,
  );
  const newCount = getNonNegativeIntFromUnknown(
    record.new_count ?? record.newCount,
  );

  if (
    oldStart == null ||
    oldCount == null ||
    newStart == null ||
    newCount == null
  ) {
    return undefined;
  }

  return {
    oldStart,
    oldCount,
    newStart,
    newCount,
  };
};

const parseToolFileDiffMetadata = (
  value: unknown,
): ToolFileDiffMetadata | undefined => {
  if (typeof value !== "object" || value == null) return undefined;
  const record = value as Record<string, unknown>;
  const rawHunks = Array.isArray(record.hunks) ? record.hunks : [];
  const hunks = rawHunks
    .map((hunk) => parseToolDiffHunk(hunk))
    .filter((hunk): hunk is ToolDiffHunk => Boolean(hunk));
  const toolName =
    typeof (record.tool_name ?? record.toolName) === "string"
      ? String(record.tool_name ?? record.toolName).trim()
      : undefined;
  const filePath =
    typeof (record.file_path ?? record.filePath) === "string"
      ? String(record.file_path ?? record.filePath).trim()
      : undefined;
  const beforeLineCount = getNonNegativeIntFromUnknown(
    record.before_line_count ?? record.beforeLineCount,
  );
  const afterLineCount = getNonNegativeIntFromUnknown(
    record.after_line_count ?? record.afterLineCount,
  );
  const deltaAdded = getNonNegativeIntFromUnknown(
    record.delta_added ?? record.deltaAdded,
  );
  const deltaRemoved = getNonNegativeIntFromUnknown(
    record.delta_removed ?? record.deltaRemoved,
  );
  const netAdded = getNonNegativeIntFromUnknown(
    record.net_added ?? record.netAdded,
  );
  const netRemoved = getNonNegativeIntFromUnknown(
    record.net_removed ?? record.netRemoved,
  );
  const fileVersion = getNonNegativeIntFromUnknown(
    record.file_version ?? record.fileVersion,
  );
  const netPartial = Boolean(record.net_partial ?? record.netPartial);

  if (
    hunks.length === 0 &&
    beforeLineCount == null &&
    afterLineCount == null &&
    !toolName &&
    !filePath
  ) {
    return undefined;
  }

  return {
    toolName,
    filePath,
    beforeLineCount,
    afterLineCount,
    deltaAdded,
    deltaRemoved,
    netAdded,
    netRemoved,
    fileVersion,
    netPartial,
    hunks,
  };
};

const parseToolResultPayload = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed.startsWith("{")) return undefined;
  try {
    const parsed = JSON.parse(trimmed);
    return typeof parsed === "object" && parsed != null
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
};

const resolveToolStatus = (
  rawToolStatus: unknown,
  toolContent: string,
): Extract<ThreadChatPart, { type: "tool" }>["status"] => {
  if (rawToolStatus === "error") return "error";
  if (rawToolStatus === "running") return "running";

  const payload = parseToolResultPayload(toolContent);
  if (payload) {
    const payloadOk = payload.ok;
    const payloadErrorCode = payload.error_code;
    if (payloadOk === false) return "error";
    if (
      typeof payloadErrorCode === "string" &&
      payloadErrorCode.trim() &&
      payloadErrorCode !== "null"
    ) {
      return "error";
    }
  }

  const trimmedContent = toolContent.trim();
  const exitCodeMatch = trimmedContent.match(/^Exit code:\s*(-?\d+)/m);
  if (exitCodeMatch?.[1]) {
    const exitCode = Number.parseInt(exitCodeMatch[1], 10);
    if (Number.isInteger(exitCode) && exitCode !== 0) {
      return "error";
    }
  }

  if (trimmedContent.startsWith("Error:")) return "error";
  return "success";
};

const normalizeMatcherText = (value?: string) =>
  value?.trim().toLowerCase() ?? "";

const getDiffHunksSignature = (hunks?: ToolDiffHunk[]) => {
  if (!hunks || hunks.length === 0) return "";
  return hunks
    .map(
      (hunk) =>
        `${hunk.oldStart},${hunk.oldCount},${hunk.newStart},${hunk.newCount}`,
    )
    .join(";");
};

const getToolFileDiffMetadataCandidates = (message: LangGraphMessage) => {
  const candidates: ToolFileDiffMetadata[] = [];

  const toolContent = messageContentToText(message.content);
  const toolPayload = parseToolResultPayload(toolContent);
  const details =
    toolPayload &&
    typeof toolPayload.details === "object" &&
    toolPayload.details != null
      ? (toolPayload.details as Record<string, unknown>)
      : undefined;
  const payloadFileDiffs = details?.file_diffs;
  if (Array.isArray(payloadFileDiffs)) {
    payloadFileDiffs.forEach((item) => {
      const parsed = parseToolFileDiffMetadata(item);
      if (parsed) candidates.push(parsed);
    });
  }

  const rawArtifact = (message as { artifact?: unknown }).artifact;
  if (typeof rawArtifact === "object" && rawArtifact != null) {
    const artifact = rawArtifact as Record<string, unknown>;
    const single = parseToolFileDiffMetadata(artifact.file_diff);
    if (single) candidates.push(single);

    const toolDiffs = artifact.tool_file_diffs;
    if (Array.isArray(toolDiffs)) {
      toolDiffs.forEach((item) => {
        const parsed = parseToolFileDiffMetadata(item);
        if (parsed) candidates.push(parsed);
      });
    }

    const legacyList = artifact.file_diffs;
    if (Array.isArray(legacyList)) {
      legacyList.forEach((item) => {
        const parsed = parseToolFileDiffMetadata(item);
        if (parsed) candidates.push(parsed);
      });
    }
  }

  const rawAdditionalKwargs = (message as { additional_kwargs?: unknown })
    .additional_kwargs;
  if (typeof rawAdditionalKwargs === "object" && rawAdditionalKwargs != null) {
    const additionalKwargs = rawAdditionalKwargs as Record<string, unknown>;
    const single = parseToolFileDiffMetadata(additionalKwargs.file_diff);
    if (single) candidates.push(single);

    const list = additionalKwargs.tool_file_diffs;
    if (Array.isArray(list)) {
      list.forEach((item) => {
        const parsed = parseToolFileDiffMetadata(item);
        if (parsed) candidates.push(parsed);
      });
    }
  }

  if (candidates.length === 0) return [];

  const seen = new Set<string>();
  return candidates.filter((candidate) => {
    const key = [
      normalizeMatcherText(candidate.toolName),
      normalizeMatcherText(candidate.filePath),
      candidate.beforeLineCount ?? "",
      candidate.afterLineCount ?? "",
      getDiffHunksSignature(candidate.hunks),
    ].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

const getToolFileDiffMetadata = (
  candidates: ToolFileDiffMetadata[],
  toolName: string,
  toolInvocation?: string,
) => {
  if (candidates.length === 0) return undefined;

  const normalizedToolName = normalizeMatcherText(toolName);
  const normalizedToolInvocation = normalizeMatcherText(toolInvocation);
  let bestCandidate = candidates[0];
  let bestScore = -1;

  candidates.forEach((candidate) => {
    let score = 0;
    if (
      candidate.toolName &&
      normalizeMatcherText(candidate.toolName) === normalizedToolName
    ) {
      score += 2;
    }
    if (
      normalizedToolInvocation &&
      candidate.filePath &&
      normalizeMatcherText(candidate.filePath) === normalizedToolInvocation
    ) {
      score += 1;
    }
    if (score > bestScore) {
      bestScore = score;
      bestCandidate = candidate;
    }
  });

  return bestCandidate;
};

const getToolChangeCountFromFileDiff = (fileDiff?: ToolFileDiffMetadata) => {
  if (!fileDiff) return undefined;
  if (fileDiff.deltaAdded != null || fileDiff.deltaRemoved != null) {
    return {
      added: fileDiff.deltaAdded ?? 0,
      removed: fileDiff.deltaRemoved ?? 0,
    };
  }
  if (fileDiff.hunks.length > 0) {
    return fileDiff.hunks.reduce(
      (acc, hunk) => ({
        added: acc.added + hunk.newCount,
        removed: acc.removed + hunk.oldCount,
      }),
      { added: 0, removed: 0 },
    );
  }

  if (
    fileDiff.beforeLineCount != null &&
    fileDiff.afterLineCount != null &&
    fileDiff.beforeLineCount !== fileDiff.afterLineCount
  ) {
    const delta = fileDiff.afterLineCount - fileDiff.beforeLineCount;
    return {
      added: delta > 0 ? delta : 0,
      removed: delta < 0 ? Math.abs(delta) : 0,
    };
  }

  return undefined;
};

const getToolNetChangeCountFromFileDiff = (fileDiff?: ToolFileDiffMetadata) => {
  if (!fileDiff) return undefined;
  if (fileDiff.netAdded == null && fileDiff.netRemoved == null) return undefined;
  return {
    added: fileDiff.netAdded ?? 0,
    removed: fileDiff.netRemoved ?? 0,
  };
};

const getToolChangeCountFromFileDiffs = (fileDiffs: ToolFileDiffMetadata[]) => {
  if (fileDiffs.length === 0) return undefined;
  let hasDiff = false;
  const total = fileDiffs.reduce(
    (acc, fileDiff) => {
      const change = getToolChangeCountFromFileDiff(fileDiff);
      if (!change) return acc;
      hasDiff = true;
      return {
        added: acc.added + change.added,
        removed: acc.removed + change.removed,
      };
    },
    { added: 0, removed: 0 },
  );
  return hasDiff ? total : undefined;
};

const getToolNetChangeCountFromFileDiffs = (fileDiffs: ToolFileDiffMetadata[]) => {
  if (fileDiffs.length === 0) return undefined;
  let hasDiff = false;
  const total = fileDiffs.reduce(
    (acc, fileDiff) => {
      const change = getToolNetChangeCountFromFileDiff(fileDiff);
      if (!change) return acc;
      hasDiff = true;
      return {
        added: acc.added + change.added,
        removed: acc.removed + change.removed,
      };
    },
    { added: 0, removed: 0 },
  );
  return hasDiff ? total : undefined;
};

const getDiffLineMetaFromFileDiff = (fileDiff?: ToolFileDiffMetadata) => {
  const firstHunk = fileDiff?.hunks[0];
  if (!firstHunk) return undefined;
  const absoluteStart =
    firstHunk.oldStart > 0
      ? firstHunk.oldStart
      : firstHunk.newStart > 0
        ? firstHunk.newStart
        : undefined;
  if (!absoluteStart) return undefined;
  return { lineOffset: absoluteStart - 1, lineMode: "absolute" as const };
};

const getDiffSectionValuesFromFileDiff = (fileDiff: ToolFileDiffMetadata) => {
  if (fileDiff.hunks.length > 0) {
    const oldValue = fileDiff.hunks
      .map(
        (hunk) =>
          `L${hunk.oldStart}${hunk.oldCount > 1 ? `-${hunk.oldStart + hunk.oldCount - 1}` : ""}: ${hunk.oldCount} line(s) before`,
      )
      .join("\n");
    const newValue = fileDiff.hunks
      .map(
        (hunk) =>
          `L${hunk.newStart}${hunk.newCount > 1 ? `-${hunk.newStart + hunk.newCount - 1}` : ""}: ${hunk.newCount} line(s) after`,
      )
      .join("\n");
    return { oldValue, newValue };
  }

  const before =
    fileDiff.beforeLineCount != null
      ? `${fileDiff.beforeLineCount} line(s)`
      : "unknown";
  const after =
    fileDiff.afterLineCount != null
      ? `${fileDiff.afterLineCount} line(s)`
      : "unknown";
  return {
    oldValue: `before: ${before}`,
    newValue: `after: ${after}`,
  };
};

const getDiffSectionsFromFileDiffs = (
  fileDiffs: ToolFileDiffMetadata[],
): ToolDiffSection[] => {
  if (fileDiffs.length === 0) return [];
  return fileDiffs.map((fileDiff, index) => {
    const diffLineMeta = getDiffLineMetaFromFileDiff(fileDiff);
    const values = getDiffSectionValuesFromFileDiff(fileDiff);
    const normalizedPath = fileDiff.filePath?.trim();
    return {
      id: `artifact-diff-${normalizedPath ?? "unknown"}-${index}`,
      filePath: normalizedPath,
      oldValue: values.oldValue,
      newValue: values.newValue,
      diffLineOffset: diffLineMeta?.lineOffset,
      diffLineMode: diffLineMeta?.lineMode,
      diffHunks: fileDiff.hunks.length > 0 ? fileDiff.hunks : undefined,
    };
  });
};

const getDiffSectionsSignature = (sections?: ToolDiffSection[]) => {
  if (!sections || sections.length === 0) return "";
  return sections
    .map((section) => {
      const hunkSignature = getDiffHunksSignature(section.diffHunks);
      return [
        section.id,
        normalizeMatcherText(section.filePath),
        section.oldValue ?? "",
        section.newValue ?? "",
        section.diffLineOffset ?? "",
        section.diffLineMode ?? "",
        hunkSignature,
      ].join("|");
    })
    .join(";");
};

const getDiffLineOffset = (
  toolName: string,
  toolCallArgs: unknown,
  toolMessageContent: string,
) => {
  if (toolName !== "edit_file" && toolName !== "write_file") {
    return { lineOffset: 0, lineMode: "relative" as const };
  }

  if (toolCallArgs && typeof toolCallArgs === "object") {
    const args = toolCallArgs as Record<string, unknown>;
    const lineStartCandidates = [
      args.old_start_line,
      args.start_line,
      args.line_start,
      args.startLine,
      args.start,
      args.line,
    ];

    for (const candidate of lineStartCandidates) {
      const lineStart = getPositiveIntFromUnknown(candidate);
      if (lineStart) {
        return { lineOffset: lineStart - 1, lineMode: "absolute" as const };
      }
    }
  }

  const hunkMatch = toolMessageContent.match(
    /^@@\s*-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s*@@/m,
  );
  if (hunkMatch?.[1]) {
    const oldStart = Number.parseInt(hunkMatch[1], 10);
    if (Number.isInteger(oldStart) && oldStart > 0) {
      return { lineOffset: oldStart - 1, lineMode: "absolute" as const };
    }
  }

  return { lineOffset: 0, lineMode: "relative" as const };
};

const parseMixedContent = (text: string): Omit<ThreadChatTextPart, "id">[] => {
  const parts: Omit<ThreadChatTextPart, "id">[] = [];
  const regex = /<think>([\s\S]*?)(?:<\/think>|$)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      const content = text.substring(lastIndex, match.index);
      if (content) parts.push({ type: "content", content });
    }
    if (match[1]) {
      parts.push({ type: "reasoning", content: match[1] });
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    const content = text.substring(lastIndex);
    if (content) parts.push({ type: "content", content });
  }

  return parts;
};

const getMessageFinishReason = (message: LangGraphMessage) => {
  if (message.type !== "ai") return undefined;
  const responseMetadata = (message as { response_metadata?: unknown })
    .response_metadata;
  if (typeof responseMetadata !== "object" || responseMetadata == null) {
    return undefined;
  }
  const finishReason = (responseMetadata as { finish_reason?: unknown })
    .finish_reason;
  return typeof finishReason === "string" ? finishReason : undefined;
};

const getAiMessageTokenUsage = (message: LangGraphMessage) => {
  if (message.type !== "ai") return undefined;

  const usageMetadata = (message as { usage_metadata?: unknown })
    .usage_metadata;
  const usage =
    typeof usageMetadata === "object" && usageMetadata != null
      ? (usageMetadata as Record<string, unknown>)
      : {};
  const responseMetadata = (message as { response_metadata?: unknown })
    .response_metadata;
  const response =
    typeof responseMetadata === "object" && responseMetadata != null
      ? (responseMetadata as Record<string, unknown>)
      : {};
  const responseTokenUsage =
    typeof response.token_usage === "object" && response.token_usage != null
      ? (response.token_usage as Record<string, unknown>)
      : {};

  const inputTokens =
    getNonNegativeIntFromUnknown(usage.input_tokens) ??
    getNonNegativeIntFromUnknown(usage.prompt_tokens) ??
    getNonNegativeIntFromUnknown(responseTokenUsage.input_tokens) ??
    getNonNegativeIntFromUnknown(responseTokenUsage.prompt_tokens);
  const outputTokens =
    getNonNegativeIntFromUnknown(usage.output_tokens) ??
    getNonNegativeIntFromUnknown(usage.completion_tokens) ??
    getNonNegativeIntFromUnknown(responseTokenUsage.output_tokens) ??
    getNonNegativeIntFromUnknown(responseTokenUsage.completion_tokens);
  const totalTokens =
    getNonNegativeIntFromUnknown(usage.total_tokens) ??
    getNonNegativeIntFromUnknown(responseTokenUsage.total_tokens) ??
    (inputTokens != null && outputTokens != null
      ? inputTokens + outputTokens
      : undefined);

  const modelName =
    typeof response.model_name === "string" ? response.model_name : undefined;
  const hasUsage =
    inputTokens != null || outputTokens != null || totalTokens != null;
  if (!hasUsage) return undefined;

  const normalizedInputTokens = inputTokens ?? 0;
  const normalizedOutputTokens = outputTokens ?? 0;
  const normalizedTotalTokens =
    totalTokens ?? normalizedInputTokens + normalizedOutputTokens;
  const hasNonZeroUsage =
    normalizedInputTokens > 0 ||
    normalizedOutputTokens > 0 ||
    normalizedTotalTokens > 0;
  if (!hasNonZeroUsage) return undefined;

  return {
    inputTokens: normalizedInputTokens,
    outputTokens: normalizedOutputTokens,
    totalTokens: normalizedTotalTokens,
    modelName,
  };
};

export const buildTokenUsageSummaryFromMessages = (
  messages: LangGraphMessage[],
  contextWindowTokens = 131072,
): ThreadChatTokenUsageSummary => {
  let userMessageCount = 0;
  let assistantMessageCount = 0;
  let toolMessageCount = 0;
  let otherMessageCount = 0;
  let assistantMessagesWithUsageCount = 0;
  let cumulativeInputTokens = 0;
  let cumulativeOutputTokens = 0;
  let cumulativeTotalTokens = 0;
  let latestInputTokens = 0;
  let latestOutputTokens = 0;
  let latestTotalTokens = 0;
  let latestModelName: string | undefined;
  let latestMessageId: string | undefined;

  messages.forEach((message, index) => {
    if (message.type === "human") {
      userMessageCount += 1;
      return;
    }
    if (message.type === "tool") {
      toolMessageCount += 1;
      return;
    }
    if (message.type !== "ai") {
      otherMessageCount += 1;
      return;
    }

    assistantMessageCount += 1;
    const usage = getAiMessageTokenUsage(message);
    if (!usage) return;

    assistantMessagesWithUsageCount += 1;
    cumulativeInputTokens += usage.inputTokens;
    cumulativeOutputTokens += usage.outputTokens;
    cumulativeTotalTokens += usage.totalTokens;
    latestInputTokens = usage.inputTokens;
    latestOutputTokens = usage.outputTokens;
    latestTotalTokens = usage.totalTokens;
    latestModelName = usage.modelName;
    latestMessageId = message.id ?? `assistant-${index}`;
  });

  const latestContextUsageRatio =
    contextWindowTokens > 0
      ? Number((latestInputTokens / contextWindowTokens).toFixed(4))
      : undefined;

  return {
    messageCount: messages.length,
    userMessageCount,
    assistantMessageCount,
    toolMessageCount,
    otherMessageCount,
    assistantMessagesWithUsageCount,
    latestInputTokens,
    latestOutputTokens,
    latestTotalTokens,
    latestContextUsageRatio,
    latestModelName,
    latestMessageId,
    cumulativeInputTokens,
    cumulativeOutputTokens,
    cumulativeTotalTokens,
    contextWindowTokens,
  };
};

const dedupeTurnMessages = (nextMessages: ThreadChatDisplayMessage[]) => {
  const lastUserIndex = [...nextMessages]
    .map((message) => message.role)
    .lastIndexOf("user");
  if (lastUserIndex < 0) return nextMessages;

  const prefix = nextMessages.slice(0, lastUserIndex + 1);
  const turn = nextMessages.slice(lastUserIndex + 1);
  const seenMessageIds = new Set<string>();
  const seenToolCallIds = new Set<string>();
  const dedupedTurn: ThreadChatDisplayMessage[] = [];

  for (let index = turn.length - 1; index >= 0; index -= 1) {
    const message = turn[index];
    if (seenMessageIds.has(message.id)) {
      continue;
    }
    seenMessageIds.add(message.id);

    if (message.role !== "tool") {
      dedupedTurn.push(message);
      continue;
    }

    const toolPart = message.parts.find(
      (part): part is Extract<ThreadChatPart, { type: "tool" }> =>
        part.type === "tool",
    );
    if (!toolPart?.toolCallId) {
      dedupedTurn.push(message);
      continue;
    }

    if (seenToolCallIds.has(toolPart.toolCallId)) {
      continue;
    }

    seenToolCallIds.add(toolPart.toolCallId);
    dedupedTurn.push(message);
  }

  dedupedTurn.reverse();
  return [...prefix, ...dedupedTurn];
};

const getToolPartFromDisplayMessage = (message: ThreadChatDisplayMessage) => {
  if (message.role !== "tool") return undefined;
  return message.parts.find(
    (part): part is Extract<ThreadChatPart, { type: "tool" }> =>
      part.type === "tool",
  );
};

const stabilizeLoadingTurnTools = (
  nextMessages: ThreadChatDisplayMessage[],
  prevMessages: ThreadChatDisplayMessage[],
  isLoading: boolean,
) => {
  if (!isLoading || prevMessages.length === 0) return nextMessages;

  const nextLastUserIndex = [...nextMessages]
    .map((message) => message.role)
    .lastIndexOf("user");
  const prevLastUserIndex = [...prevMessages]
    .map((message) => message.role)
    .lastIndexOf("user");

  if (nextLastUserIndex < 0 || prevLastUserIndex < 0) return nextMessages;

  const nextUserAnchor = nextMessages[nextLastUserIndex]?.id;
  const prevUserAnchor = prevMessages[prevLastUserIndex]?.id;
  if (!nextUserAnchor || !prevUserAnchor || nextUserAnchor !== prevUserAnchor) {
    return nextMessages;
  }

  const prevTurn = prevMessages.slice(prevLastUserIndex + 1);
  const prevCompletedToolByCallId = new Map<string, ThreadChatDisplayMessage>();
  prevTurn.forEach((message) => {
    const part = getToolPartFromDisplayMessage(message);
    if (!part?.toolCallId) return;
    if (part.status === "running") return;
    prevCompletedToolByCallId.set(part.toolCallId, message);
  });

  return nextMessages.map((message, index) => {
    if (index <= nextLastUserIndex) return message;

    const currentPart = getToolPartFromDisplayMessage(message);
    if (!currentPart?.toolCallId || currentPart.status !== "running") {
      return message;
    }

    const prevCompletedMessage = prevCompletedToolByCallId.get(
      currentPart.toolCallId,
    );
    if (!prevCompletedMessage) return message;
    return prevCompletedMessage;
  });
};

export const normalizeThreadChatMessages = ({
  messages,
  isLoading,
  enableSyntheticPendingToolMessage,
  stabilizeStoreKey,
}: {
  messages: LangGraphMessage[];
  isLoading: boolean;
  enableSyntheticPendingToolMessage: boolean;
  stabilizeStoreKey: string;
}) => {
  const normalized: ThreadChatDisplayMessage[] = [];
  const completedToolCallIds = new Set(
    messages
      .filter(
        (message): message is LangGraphMessage & { type: "tool" } =>
          message.type === "tool",
      )
      .map((message) => message.tool_call_id?.trim())
      .filter((toolCallId): toolCallId is string => Boolean(toolCallId)),
  );

  messages.forEach((message, index) => {
    if (message.type === "human" || message.type === "ai") {
      const messageId = message.id ?? `${message.type}-${index}`;
      const content = messageContentToText(message.content);
      const finishReason = getMessageFinishReason(message);
      const signature = `${message.type}|${messageId}|${content}|${finishReason ?? ""}`;
      const cachedMessage = normalizedMessageCache.get(message);

      if (cachedMessage?.signature === signature) {
        normalized.push(cachedMessage.message);
      } else {
        const parsed = parseMixedContent(content);
        const parts = parsed.map((part, partIndex) => ({
          ...part,
          id: `${messageId}-${partIndex}`,
        }));
        if (parts.length > 0) {
          const normalizedMessage: ThreadChatDisplayMessage = {
            id: messageId,
            role: message.type === "human" ? "user" : "assistant",
            parts,
            finishReason,
          };

          normalizedMessageCache.set(message, {
            signature,
            message: normalizedMessage,
          });
          normalized.push(normalizedMessage);
        }
      }

      if (message.type === "ai" && enableSyntheticPendingToolMessage) {
        const pendingToolCalls = getAiToolCalls(message);
        pendingToolCalls.forEach((toolCall) => {
          const toolCallId = toolCall.id.trim();
          if (!toolCallId || completedToolCallIds.has(toolCallId)) return;

          const toolName =
            typeof toolCall.name === "string" && toolCall.name.trim()
              ? toolCall.name.trim()
              : "工具调用";
          const toolInvocation = getToolInvocation(toolName, toolCall.args);
          const toolChangeCount = getToolChangeCount(
            toolName,
            toolCall.args,
            true,
          );
          const diffValues = getToolDiffValues(toolName, toolCall.args, true);
          const diffLineMeta = getDiffLineOffset(toolName, toolCall.args, "");

          normalized.push({
            id: `tool-call-${toolCallId}`,
            role: "tool",
            parts: [
              {
                id: `tool-call-${toolCallId}-part`,
                type: "tool",
                toolName,
                toolInvocation,
                toolAddedCount: toolChangeCount.added,
                toolRemovedCount: toolChangeCount.removed,
                toolCallId,
                status: "running",
                content: "",
                contentFormat: "shell",
                diffOldValue: diffValues.oldValue,
                diffNewValue: diffValues.newValue,
                diffLineOffset: diffLineMeta.lineOffset,
                diffLineMode: diffLineMeta.lineMode,
                diffHunks: undefined,
              },
            ],
          });
        });
      }
      return;
    }

    if (message.type === "tool") {
      const toolName = message.name?.trim() || "工具调用";
      const normalizedToolCallId = message.tool_call_id?.trim() ?? "";
      const messageId = normalizedToolCallId
        ? `tool-call-${normalizedToolCallId}`
        : message.id ?? `${message.type}-${index}`;
      const toolCallId =
        normalizedToolCallId || `${TOOL_CALL_FALLBACK_PREFIX}${messageId}`;
      const rawToolStatus = (message as { status?: unknown }).status;
      const toolContent = messageContentToText(message.content);
      const toolStatus = resolveToolStatus(rawToolStatus, toolContent);
      const isToolRunning = toolStatus === "running";
      const shouldFreezeToolPayload = isToolRunning;
      const toolCallArgs = getToolCallArgsFromPreviousAiMessage(
        messages,
        index,
        toolCallId,
      );
      const toolInvocation = getToolInvocation(toolName, toolCallArgs);
      const toolFileDiffCandidates = getToolFileDiffMetadataCandidates(message);
      const toolFileDiff = getToolFileDiffMetadata(
        toolFileDiffCandidates,
        toolName,
        toolInvocation,
      );
      const resolvedToolInvocation =
        toolInvocation || toolFileDiff?.filePath?.trim() || "";
      const metadataDiffSections =
        getDiffSectionsFromFileDiffs(toolFileDiffCandidates);
      const metadataPrimaryDiffValues =
        toolFileDiff != null
          ? getDiffSectionValuesFromFileDiff(toolFileDiff)
          : undefined;
      const toolDisplayContent = resolveToolDisplayContent(
        toolName,
        toolContent,
        toolCallArgs,
        resolvedToolInvocation,
        shouldFreezeToolPayload,
      );
      const fallbackToolChangeCount = getToolChangeCount(
        toolName,
        toolCallArgs,
        shouldFreezeToolPayload,
      );
      const metadataToolChangeCount =
        getToolChangeCountFromFileDiffs(toolFileDiffCandidates);
      const metadataToolNetChangeCount =
        getToolNetChangeCountFromFileDiffs(toolFileDiffCandidates);
      const strictApplyPatchChangeCount =
        toolName === "apply_patch" ? metadataToolNetChangeCount : undefined;
      const toolChangeCount =
        toolName === "apply_patch"
          ? strictApplyPatchChangeCount
          : (metadataToolChangeCount ?? fallbackToolChangeCount);
      const fallbackDiffValues = getToolDiffValues(
        toolName,
        toolCallArgs,
        shouldFreezeToolPayload,
      );
      const shouldUseMetadataDiffValues =
        !shouldFreezeToolPayload &&
        Boolean(metadataPrimaryDiffValues) &&
        !fallbackDiffValues.oldValue.trim() &&
        !fallbackDiffValues.newValue.trim();
      const diffValues = shouldUseMetadataDiffValues
        ? metadataPrimaryDiffValues!
        : fallbackDiffValues;
      const fallbackDiffLineMeta = getDiffLineOffset(
        toolName,
        toolCallArgs,
        toolContent,
      );
      const diffLineMeta =
        getDiffLineMetaFromFileDiff(toolFileDiff) ?? fallbackDiffLineMeta;
      const diffHunks = toolFileDiff?.hunks;
      const diffHunksSignature = getDiffHunksSignature(diffHunks);
      const toolContentSignature = shouldFreezeToolPayload ? "" : toolContent;
      const toolArgsSignature =
        shouldFreezeToolPayload || toolCallArgs == null
          ? ""
          : safeStringify(toolCallArgs);
      const shouldUseMetadataDiffSections =
        !shouldFreezeToolPayload &&
        metadataDiffSections.length > 0 &&
        !fallbackDiffValues.oldValue.trim() &&
        !fallbackDiffValues.newValue.trim();
      const diffSections = shouldUseMetadataDiffSections
        ? metadataDiffSections
        : undefined;
      const diffSectionsSignature = getDiffSectionsSignature(diffSections);
      const contentFormat: "shell" | "diff" =
        !shouldFreezeToolPayload &&
        (isDiffToolName(toolName) || metadataDiffSections.length > 0)
          ? "diff"
          : "shell";
      const signature = `${message.type}|${messageId}|${toolCallId}|${toolName}|${resolvedToolInvocation}|${toolChangeCount?.added ?? ""}|${toolChangeCount?.removed ?? ""}|${metadataToolNetChangeCount?.added ?? ""}|${metadataToolNetChangeCount?.removed ?? ""}|${toolStatus}|${contentFormat}|${toolContentSignature}|${diffValues.oldValue}|${diffValues.newValue}|${diffLineMeta.lineOffset}|${diffLineMeta.lineMode}|${diffHunksSignature}|${diffSectionsSignature}|${toolArgsSignature}`;
      const cachedMessage = normalizedMessageCache.get(message);

      if (cachedMessage?.signature === signature) {
        normalized.push(cachedMessage.message);
        return;
      }

      const normalizedMessage: ThreadChatDisplayMessage = {
        id: messageId,
        role: "tool",
        parts: [
          {
            id: `${messageId}-tool`,
            type: "tool",
            toolName,
            toolInvocation: resolvedToolInvocation,
            toolAddedCount: toolChangeCount?.added,
            toolRemovedCount: toolChangeCount?.removed,
            toolNetAddedCount: metadataToolNetChangeCount?.added,
            toolNetRemovedCount: metadataToolNetChangeCount?.removed,
            toolCallId,
            status: toolStatus,
            content: toolDisplayContent,
            contentFormat,
            diffOldValue: diffValues.oldValue,
            diffNewValue: diffValues.newValue,
            diffLineOffset: diffLineMeta.lineOffset,
            diffLineMode: diffLineMeta.lineMode,
            diffHunks,
            diffSections,
          },
        ],
      };

      normalizedMessageCache.set(message, {
        signature,
        message: normalizedMessage,
      });
      normalized.push(normalizedMessage);
    }
  });

  const stabilizedMessages = stabilizeLoadingTurnTools(
    normalized,
    stabilizedMessagesStore.get(stabilizeStoreKey) ?? [],
    isLoading,
  );
  const stabilizedDeduped = dedupeTurnMessages(stabilizedMessages);
  stabilizedMessagesStore.set(stabilizeStoreKey, stabilizedDeduped);
  return stabilizedDeduped;
};

export const clearStabilizedThreadMessages = (stabilizeStoreKey: string) => {
  stabilizedMessagesStore.delete(stabilizeStoreKey);
};

const toEnvironmentDisplayStatus = (
  status: SandboxBootstrapStatus,
): EnvironmentInitDisplay["status"] => {
  if (status === "success") return "success";
  if (status === "error") return "error";
  return "running";
};

export const buildEnvironmentDisplayFromBootstrap = (
  payload: SandboxBootstrapResult,
): EnvironmentInitDisplay | null => {
  const normalizedError =
    typeof payload.error === "string" && payload.error.trim().length > 0
      ? payload.error.trim()
      : undefined;
  const hasDisplayHistory =
    payload.logs.length > 0 ||
    payload.steps.length > 0 ||
    Boolean(normalizedError) ||
    Boolean(payload.updated_at) ||
    Boolean(payload.finished_at) ||
    Boolean(payload.request_id);

  if (payload.status === "idle") {
    if (!hasDisplayHistory) return null;
    return {
      id: payload.request_id?.trim() || `bootstrap-idle-${Date.now()}`,
      status: normalizedError ? "error" : "success",
      title: normalizedError ? "环境初始化状态（异常）" : "环境初始化状态",
      steps: payload.steps.length > 0 ? payload.steps : DEFAULT_ENV_INIT_STEPS,
      logs:
        payload.logs.length > 0
          ? payload.logs
          : [
              {
                level: normalizedError ? "error" : "info",
                message:
                  normalizedError ??
                  "环境初始化信息已保留，可重新发送消息触发初始化。",
              },
            ],
      error: normalizedError,
      runId: payload.run_id?.trim() || undefined,
      runStatus: payload.run_status?.trim() || undefined,
    };
  }

  return {
    id: payload.request_id?.trim() || `bootstrap-${Date.now()}`,
    status: toEnvironmentDisplayStatus(payload.status),
    steps: payload.steps.length > 0 ? payload.steps : DEFAULT_ENV_INIT_STEPS,
    logs: payload.logs,
    error: normalizedError,
    runId: payload.run_id?.trim() || undefined,
    runStatus: payload.run_status?.trim() || undefined,
  };
};

export const buildEnvironmentInitTitle = (display: EnvironmentInitDisplay) =>
  display.title ??
  (display.status === "running"
    ? "环境初始化中"
    : display.status === "success"
      ? "环境初始化完成"
      : "环境初始化失败");

export const buildEnvironmentResetDisplay = (
  payload: SandboxBootstrapResult,
): EnvironmentInitDisplay => {
  const resetError =
    typeof payload.reset_error === "string" && payload.reset_error.trim()
      ? payload.reset_error.trim()
      : undefined;
  const resetSuccess = payload.reset_success !== false && !resetError;
  const defaultMessage = resetSuccess
    ? "环境已重置，请重新发送消息开始初始化。"
    : (resetError ?? "环境重置失败，请重试。");

  return {
    id: `bootstrap-reset-${Date.now()}`,
    status: resetSuccess ? "success" : "error",
    title: resetSuccess ? "环境初始化已重置" : "环境初始化重置失败",
    steps: DEFAULT_ENV_INIT_STEPS,
    logs:
      payload.logs.length > 0
        ? payload.logs
        : [
            {
              level: resetSuccess ? "info" : "error",
              message: defaultMessage,
            },
          ],
    error: resetError,
  };
};

export const buildEnvironmentInitOutput = (display: EnvironmentInitDisplay) => {
  const lines = [`$ ${buildEnvironmentInitTitle(display)}`];

  display.steps.forEach((step) => {
    const detail = step.detail?.trim();
    const status = ENV_INIT_STATUS_TEXT[step.status];
    if (detail) {
      lines.push(`[STEP] ${step.title}: ${status} (${detail})`);
    } else {
      lines.push(`[STEP] ${step.title}: ${status}`);
    }
  });

  if (display.logs.length > 0) {
    lines.push("");
    lines.push("# Logs");
    display.logs.forEach((log) => {
      const message = log.message.trim();
      if (!message) return;
      const level = ENV_LOG_LEVEL_TEXT[log.level ?? ""] ?? "INFO";
      lines.push(`[${level}] ${message}`);
    });
  }

  if (display.runId) {
    lines.push("");
    if (display.runStatus?.trim()) {
      lines.push(`[RUN] ${display.runStatus.trim()} (${display.runId})`);
    } else {
      lines.push(`[RUN] ${display.runId}`);
    }
  }

  if (display.error?.trim()) {
    lines.push("");
    lines.push(`[ERROR] ${display.error.trim()}`);
  }

  return lines.join("\n");
};

export const isAbortError = (error: unknown) => {
  if (error instanceof DOMException) {
    return error.name === "AbortError";
  }
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
};

export const getErrorStatusCode = (error: unknown) => {
  if (!error || typeof error !== "object") return undefined;
  const record = error as Record<string, unknown>;
  const status = record.status;
  if (typeof status === "number") return status;
  if (typeof status === "string") {
    const parsed = Number.parseInt(status, 10);
    if (Number.isFinite(parsed)) return parsed;
  }

  const response = record.response;
  if (!response || typeof response !== "object") return undefined;
  const responseStatus = (response as Record<string, unknown>).status;
  if (typeof responseStatus === "number") return responseStatus;
  if (typeof responseStatus === "string") {
    const parsed = Number.parseInt(responseStatus, 10);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
};

export const getErrorMessageText = (error: unknown) => {
  if (!error) return "";
  if (typeof error === "string") return error.trim();
  if (error instanceof Error) return error.message.trim();
  if (typeof error !== "object") return "";

  const record = error as Record<string, unknown>;
  const directCandidates = [record.message, record.detail, record.error];
  for (const candidate of directCandidates) {
    if (typeof candidate === "string" && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }

  const nestedError = record.error;
  if (nestedError && typeof nestedError === "object") {
    const nestedMessage = (nestedError as Record<string, unknown>).message;
    if (typeof nestedMessage === "string" && nestedMessage.trim().length > 0) {
      return nestedMessage.trim();
    }
  }

  return "";
};
