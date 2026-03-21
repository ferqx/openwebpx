import {
  type ThreadChatDisplayMessage,
  type ThreadChatPart
} from '@/business/thread-chat/types';

export type CopyMeta = {
  canCopy: boolean;
  copyText: string;
};

export type MessageRenderItem =
  | {
      type: 'message';
      sourceIndex: number;
      message: ThreadChatDisplayMessage;
    }
  | {
      type: 'tool-group';
      sourceIndex: number;
      id: string;
      tools: ThreadChatDisplayMessage[];
      defaultOpen: boolean;
    };

export type MessagePartGroups = {
  reasoning: Extract<ThreadChatPart, { type: 'reasoning' }>[];
  content: Extract<ThreadChatPart, { type: 'content' }>[];
  tools: Extract<ThreadChatPart, { type: 'tool' }>[];
  environments: Extract<ThreadChatPart, { type: 'environment' }>[];
};

type IncrementalCache<T> = {
  messages: ThreadChatDisplayMessage[];
  value: T;
};

const findStablePrefixLength = (
  previous: ThreadChatDisplayMessage[],
  next: ThreadChatDisplayMessage[]
) => {
  const maxLength = Math.min(previous.length, next.length);
  let index = 0;
  while (index < maxLength && previous[index] === next[index]) {
    index += 1;
  }
  return index;
};

let copyMetaCache: IncrementalCache<CopyMeta[]> | null = null;
let turnSummaryCache: IncrementalCache<ThreadChatTurnFileChangeSummary[]> | null =
  null;
let renderItemsCache: IncrementalCache<MessageRenderItem[]> | null = null;

const normalizeToolTargets = (toolInvocation?: string) =>
  (toolInvocation ?? '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

const toDisplayName = (rawPath: string) => {
  const trimmed = rawPath.trim().replace(/^['"]|['"]$/g, '');
  if (!trimmed) return '';
  const segments = trimmed.split('/').filter(Boolean);
  return segments[segments.length - 1] ?? trimmed;
};

const extractFindTarget = (command: string) => {
  const quotedNameMatch = command.match(/-name\s+['"]([^'"]+)['"]/i);
  if (quotedNameMatch?.[1]?.trim()) return quotedNameMatch[1].trim();

  const plainNameMatch = command.match(/-name\s+([^\s]+)/i);
  if (plainNameMatch?.[1]?.trim()) return plainNameMatch[1].trim();

  return '';
};

const extractExecutePath = (command: string) => {
  const patterns = [
    /^cat\s+(?:-[^\s]+\s+)*(['"]?)([^'"|\s;]+)\1/i,
    /^head\s+(?:-[^\s]+\s+)*(['"]?)([^'"|\s;]+)\1/i,
    /^tail\s+(?:-[^\s]+\s+)*(['"]?)([^'"|\s;]+)\1/i,
    /^ls\s+(?:-[^\s]+\s+)*(['"]?)([^'"|\s;]+)\1/i,
    /^sed\b(?:.*\s)(['"]?)([^'"|\s;]+)\1$/i
  ];

  for (const pattern of patterns) {
    const match = command.match(pattern);
    const path = match?.[2]?.trim();
    if (path) return path;
  }

  return '';
};

const extractSearchKeyword = (command: string) => {
  const quotedMatch = command.match(/['"]([^'"]+)['"]/);
  if (quotedMatch?.[1]?.trim()) return quotedMatch[1].trim();

  const parts = command.split(/\s+/).map((part) => part.trim()).filter(Boolean);
  for (let index = 1; index < parts.length; index += 1) {
    const part = parts[index];
    if (!part) continue;
    if (part.startsWith('-')) continue;
    if (part.startsWith('/')) continue;
    return part;
  }

  return '';
};

const getExecuteDisplayTitle = (toolInvocation?: string) => {
  const command = toolInvocation?.trim() ?? '';
  if (!command) return '执行命令';

  const [commandName = ''] = command.split(/\s+/, 1);
  const normalizedName = commandName.toLowerCase();

  if (['rg', 'grep', 'find', 'fd'].includes(normalizedName)) {
    if (['find', 'fd'].includes(normalizedName)) {
      const target = extractFindTarget(command);
      return target ? `查找 ${target}` : '查找文件';
    }
    const keyword = extractSearchKeyword(command);
    return keyword ? `搜索 ${keyword}` : '搜索内容';
  }

  if (normalizedName === 'ls') {
    const path = extractExecutePath(command);
    const displayName = path ? toDisplayName(path) : '';
    return displayName ? `查看 ${displayName} 目录` : '查看目录';
  }

  if (['cat', 'sed', 'head', 'tail'].includes(normalizedName)) {
    const path = extractExecutePath(command);
    const displayName = path ? toDisplayName(path) : '';
    return displayName ? `浏览 ${displayName}` : '浏览文件';
  }

  return `执行 ${command}`;
};

export const getToolTitleHighlightText = (
  toolName: string,
  toolInvocation?: string
) => {
  const normalizedInvocation = toolInvocation?.trim();
  if (!normalizedInvocation) return undefined;

  if (toolName === 'execute') {
    const [commandName = ''] = normalizedInvocation.split(/\s+/, 1);
    const normalizedName = commandName.toLowerCase();

    if (['cat', 'sed', 'head', 'tail', 'ls'].includes(normalizedName)) {
      const path = extractExecutePath(normalizedInvocation);
      return path ? toDisplayName(path) : undefined;
    }

    if (['find', 'fd'].includes(normalizedName)) {
      return extractFindTarget(normalizedInvocation) || undefined;
    }

    return undefined;
  }

  if (toolName === 'update_plan') return undefined;

  const targets = normalizeToolTargets(toolInvocation);
  if (targets.length !== 1) return undefined;
  return toDisplayName(targets[0] ?? '');
};

export const getToolTitleTooltip = (
  toolName: string,
  toolInvocation?: string
) => {
  const normalizedInvocation = toolInvocation?.trim();
  if (!normalizedInvocation) return undefined;

  if (toolName === 'update_plan') return undefined;

  if (toolName === 'execute') {
    const [commandName = ''] = normalizedInvocation.split(/\s+/, 1);
    const normalizedName = commandName.toLowerCase();

    if (['cat', 'sed', 'head', 'tail', 'ls'].includes(normalizedName)) {
      return extractExecutePath(normalizedInvocation) || undefined;
    }

    if (['find', 'fd'].includes(normalizedName)) {
      return extractFindTarget(normalizedInvocation) || undefined;
    }

    if (['rg', 'grep'].includes(normalizedName)) {
      return extractSearchKeyword(normalizedInvocation) || undefined;
    }
  }

  const shortTitle = getToolTitle(toolName, toolInvocation);
  if (shortTitle.includes(normalizedInvocation)) return undefined;

  return normalizedInvocation;
};

export const getToolTitle = (toolName: string, toolInvocation?: string) => {
  const toolNameLabelMap: Record<string, string> = {
    update_plan: '更新计划',
    apply_patch: '编辑文件',
    edit_file: '编辑文件',
    write_file: '写入文件',
    read_file: '浏览文件',
    open_file: '浏览文件',
    view_file: '浏览文件',
    ls: '浏览文件'
  };
  const targets = normalizeToolTargets(toolInvocation);
  const displayTargets = targets.map((target) => toDisplayName(target)).filter(Boolean);

  const displayToolName =
    toolName === 'execute'
      ? getExecuteDisplayTitle(toolInvocation)
      : (toolNameLabelMap[toolName] ?? toolName);
  if (toolName === 'execute' || toolName === 'update_plan') return displayToolName;
  if (displayTargets.length === 1) return `${displayToolName} ${displayTargets[0]}`;
  if (displayTargets.length > 1) return `${displayToolName} ${displayTargets.length} 个文件`;

  const normalizedInvocation = toolInvocation?.trim();
  if (!normalizedInvocation) return displayToolName;
  return `${displayToolName} ${normalizedInvocation}`;
};

export const toShellMarkdown = (content: string) => {
  const normalized = content?.trim() ? content : '无输出';
  const escaped = normalized.replace(/```/g, '``\\`');
  return `\`\`\`shell\n${escaped}\n\`\`\``;
};

export const groupMessageParts = (parts: ThreadChatPart[]): MessagePartGroups =>
  parts.reduce<MessagePartGroups>(
    (acc, part) => {
      if (part.type === 'reasoning') {
        acc.reasoning.push(part);
        return acc;
      }
      if (part.type === 'content') {
        acc.content.push(part);
        return acc;
      }
      if (part.type === 'environment') {
        acc.environments.push(part);
        return acc;
      }
      acc.tools.push(part);
      return acc;
    },
    { reasoning: [], content: [], tools: [], environments: [] }
  );

export const shouldIgnoreToolDiffStats = (
  part: Extract<ThreadChatPart, { type: 'tool' }>
) => part.toolName === 'apply_patch' && part.status === 'error';

export const getToolChangeDisplayState = (
  part: Extract<ThreadChatPart, { type: 'tool' }>
) => {
  if (shouldIgnoreToolDiffStats(part)) {
    return {
      added: 0,
      removed: 0,
      showAdded: false,
      showRemoved: false
    };
  }

  const added = Math.max(0, part.toolAddedCount ?? 0);
  const removed = Math.max(0, part.toolRemovedCount ?? 0);

  return {
    added,
    removed,
    showAdded: part.contentFormat === 'diff' || added > 0,
    showRemoved: part.contentFormat === 'diff' || removed > 0
  };
};

export const shouldRenderToolDiffContent = (
  part: Extract<ThreadChatPart, { type: 'tool' }>
) => part.contentFormat === 'diff' && part.status !== 'error';

export const shouldRenderMessagePartsInOriginalOrder = (
  message: ThreadChatDisplayMessage
) =>
  message.role === 'assistant' &&
  message.parts.some((part) => part.type === 'tool');

export const areMessagePartsEqual = (
  prevParts: ThreadChatPart[],
  nextParts: ThreadChatPart[]
) => {
  const areDiffHunksEqual = (
    prevHunks?: Extract<ThreadChatPart, { type: 'tool' }>['diffHunks'],
    nextHunks?: Extract<ThreadChatPart, { type: 'tool' }>['diffHunks']
  ) => {
    if (prevHunks === nextHunks) return true;
    if (!prevHunks && !nextHunks) return true;
    if (!prevHunks || !nextHunks) return false;
    if (prevHunks.length !== nextHunks.length) return false;

    for (let index = 0; index < prevHunks.length; index += 1) {
      const prevHunk = prevHunks[index];
      const nextHunk = nextHunks[index];
      if (!prevHunk || !nextHunk) return false;
      if (
        prevHunk.oldStart !== nextHunk.oldStart ||
        prevHunk.oldCount !== nextHunk.oldCount ||
        prevHunk.newStart !== nextHunk.newStart ||
        prevHunk.newCount !== nextHunk.newCount
      ) {
        return false;
      }
    }
    return true;
  };

  if (prevParts === nextParts) return true;
  if (prevParts.length !== nextParts.length) return false;

  for (let index = 0; index < prevParts.length; index += 1) {
    const prevPart = prevParts[index];
    const nextPart = nextParts[index];
    if (!nextPart) return false;
    if (prevPart.type !== nextPart.type || prevPart.id !== nextPart.id) {
      return false;
    }

    if (prevPart.type === 'tool' && nextPart.type === 'tool') {
      if (
        prevPart.toolName !== nextPart.toolName ||
        prevPart.toolInvocation !== nextPart.toolInvocation ||
        prevPart.toolAddedCount !== nextPart.toolAddedCount ||
        prevPart.toolRemovedCount !== nextPart.toolRemovedCount ||
        prevPart.toolNetAddedCount !== nextPart.toolNetAddedCount ||
        prevPart.toolNetRemovedCount !== nextPart.toolNetRemovedCount ||
        prevPart.toolCallId !== nextPart.toolCallId ||
        prevPart.status !== nextPart.status ||
        prevPart.content !== nextPart.content ||
        prevPart.contentFormat !== nextPart.contentFormat ||
        prevPart.diffOldValue !== nextPart.diffOldValue ||
        prevPart.diffNewValue !== nextPart.diffNewValue ||
        prevPart.diffLineOffset !== nextPart.diffLineOffset ||
        prevPart.diffLineMode !== nextPart.diffLineMode ||
        !areDiffHunksEqual(prevPart.diffHunks, nextPart.diffHunks)
      ) {
        return false;
      }
      continue;
    }

    if (prevPart.type === 'environment' && nextPart.type === 'environment') {
      if (
        prevPart.title !== nextPart.title ||
        prevPart.status !== nextPart.status ||
        prevPart.output !== nextPart.output ||
        prevPart.error !== nextPart.error ||
        prevPart.runId !== nextPart.runId ||
        prevPart.runStatus !== nextPart.runStatus
      ) {
        return false;
      }
      continue;
    }

    if (
      (prevPart.type === 'reasoning' && nextPart.type === 'reasoning') ||
      (prevPart.type === 'content' && nextPart.type === 'content')
    ) {
      if (prevPart.content !== nextPart.content) {
        return false;
      }
      continue;
    }

    return false;
  }

  return true;
};

export const areMessagesEqual = (
  prevMessage: ThreadChatDisplayMessage,
  nextMessage: ThreadChatDisplayMessage
) => {
  if (prevMessage === nextMessage) return true;
  if (prevMessage.id !== nextMessage.id) return false;
  if (prevMessage.role !== nextMessage.role) return false;
  if (prevMessage.finishReason !== nextMessage.finishReason) return false;
  return areMessagePartsEqual(prevMessage.parts, nextMessage.parts);
};

export const buildMessageCopyText = (message: ThreadChatDisplayMessage) => {
  const sections: string[] = [];

  message.parts.forEach((part) => {
    if (part.type === 'reasoning') {
      const content = part.content.trim();
      if (content) sections.push(`[思考]\n${content}`);
      return;
    }

    if (part.type === 'content') {
      const content = part.content.trim();
      if (content) sections.push(content);
      return;
    }

    if (part.type === 'environment') {
      const output = part.output.trim();
      sections.push(`[${part.title || '环境初始化'}]`);
      if (output) sections.push(output);
      return;
    }

    const title = getToolTitle(part.toolName, part.toolInvocation);
    if (part.contentFormat === 'diff') {
      const oldValue = part.diffOldValue ?? '';
      const newValue = part.diffNewValue ?? '';
      sections.push(`[${title}]`);
      sections.push(`--- old\n${oldValue}`);
      sections.push(`+++ new\n${newValue}`);
      return;
    }

    const content = part.content.trim();
    sections.push(`[${title}]`);
    if (content) sections.push(content);
  });

  return sections.join('\n\n').trim();
};

const buildAssistantFinalReplyCopyText = (
  message: ThreadChatDisplayMessage
) => {
  if (message.role !== 'assistant') return '';

  const contentSections = message.parts
    .filter(
      (part): part is Extract<ThreadChatPart, { type: 'content' }> =>
        part.type === 'content'
    )
    .map((part) => part.content.trim())
    .filter(Boolean);

  return contentSections.join('\n\n').trim();
};

export const getCopyMetaList = (chatMessages: ThreadChatDisplayMessage[]) => {
  const cached = copyMetaCache;
  if (cached?.messages === chatMessages) {
    return cached.value;
  }

  const reuseCachedCopyMeta = (index: number, nextMeta: CopyMeta) => {
    const cachedMeta = cached?.value[index];
    if (!cachedMeta) return nextMeta;
    if (
      cachedMeta.canCopy === nextMeta.canCopy &&
      cachedMeta.copyText === nextMeta.copyText
    ) {
      return cachedMeta;
    }
    return nextMeta;
  };

  const copyMeta: CopyMeta[] = chatMessages.map(() => ({
    canCopy: false,
    copyText: ''
  }));

  let startIndex = 0;
  if (cached) {
    const stablePrefixLength = findStablePrefixLength(cached.messages, chatMessages);
    const reuseUntilIndex = Math.max(
      0,
      cached.messages
        .slice(0, stablePrefixLength)
        .map((message) => message.role)
        .lastIndexOf('user')
    );

    for (let index = 0; index < reuseUntilIndex; index += 1) {
      copyMeta[index] = cached.value[index] ?? copyMeta[index]!;
    }
    startIndex = reuseUntilIndex;
  }

  for (let index = startIndex; index < chatMessages.length; index += 1) {
    const message = chatMessages[index];
    if (!message) continue;

    if (message.role === 'user') {
      copyMeta[index] = reuseCachedCopyMeta(index, {
        canCopy: true,
        copyText: buildMessageCopyText(message)
      });
      continue;
    }

    if (message.role !== 'assistant') {
      copyMeta[index] = reuseCachedCopyMeta(index, copyMeta[index]!);
      continue;
    }

    let end = index;
    let lastAssistantIndex =
      message.finishReason !== 'tool_calls' ? index : -1;

    while (end + 1 < chatMessages.length) {
      const nextMessage = chatMessages[end + 1];
      if (!nextMessage || nextMessage.role === 'user') break;
      end += 1;
      if (
        nextMessage.role === 'assistant' &&
        nextMessage.finishReason !== 'tool_calls'
      ) {
        lastAssistantIndex = end;
      }
    }

    if (lastAssistantIndex < 0) {
      index = end;
      continue;
    }

    const assistantCopyText = buildAssistantFinalReplyCopyText(
      chatMessages[lastAssistantIndex] ?? message
    );
    // 复制入口应挂在当前轮最后一个可见 AI 块上，避免 assistant 文本后仍有
    // tool/status 行时，取消或中断把按钮留在回合中间。
    copyMeta[end] = reuseCachedCopyMeta(end, {
      canCopy: assistantCopyText.length > 0,
      copyText: assistantCopyText
    });

    index = end;
  }

  copyMetaCache = {
    messages: chatMessages,
    value: copyMeta
  };
  return copyMeta;
};

type ToolPart = Extract<ThreadChatPart, { type: 'tool' }>;

export type ThreadChatConversationFileChange = {
  id: string;
  filePath: string;
  toolName: string;
  added: number;
  removed: number;
  netAdded: number;
  netRemoved: number;
  latestAdded: number;
  latestRemoved: number;
  editCount: number;
  lastSourceIndex: number;
  diffOldValue: string;
  diffNewValue: string;
  diffLineOffset?: number;
  diffLineMode?: ToolPart['diffLineMode'];
  diffHunks?: ToolPart['diffHunks'];
};

export type ThreadChatUserTurn = {
  userIndex: number;
  endIndex: number;
};

export type ThreadChatTurnFileChangeSummary = {
  id: string;
  turnIndex: number;
  userIndex: number;
  endIndex: number;
  fileChanges: ThreadChatConversationFileChange[];
};

type LineRange = {
  start: number;
  end: number;
};

type AggregatedFileChange = ThreadChatConversationFileChange & {
  preciseAddedRanges: LineRange[];
  preciseRemovedRanges: LineRange[];
  fallbackAdded: number;
  fallbackRemoved: number;
};

const isFileDiffToolPart = (part: ToolPart) =>
  part.contentFormat === 'diff' ||
  (part.toolAddedCount ?? 0) > 0 ||
  (part.toolRemovedCount ?? 0) > 0;

const normalizeFilePath = (toolInvocation?: string) => toolInvocation?.trim() ?? '';
const concatDiffText = (previous?: string, current?: string) => {
  const chunks = [previous, current]
    .map((value) => value?.trim() ?? '')
    .filter(Boolean);
  return chunks.join('\n\n');
};

const mergeLineRanges = (ranges: LineRange[]) => {
  if (ranges.length <= 1) return ranges;

  const sorted = [...ranges].sort((left, right) => left.start - right.start);
  const merged: LineRange[] = [sorted[0]!];

  for (let index = 1; index < sorted.length; index += 1) {
    const current = sorted[index]!;
    const previous = merged[merged.length - 1]!;

    if (current.start <= previous.end + 1) {
      previous.end = Math.max(previous.end, current.end);
      continue;
    }

    merged.push({ ...current });
  }

  return merged;
};

const getLineRangeSize = (ranges: LineRange[]) =>
  mergeLineRanges(ranges).reduce((total, range) => total + (range.end - range.start + 1), 0);

const getPreciseRangesFromToolPart = (part: ToolPart) => {
  const removedRanges: LineRange[] = [];
  const addedRanges: LineRange[] = [];

  // apply_patch 的 metadata hunks 在部分场景下是近似范围（且可能截断），
  // 用它做文件级累计会放大统计；这里统一回退到 toolAdded/Removed 计数。
  if (part.toolName === 'apply_patch') {
    return { addedRanges, removedRanges };
  }

  if (part.diffHunks && part.diffHunks.length > 0) {
    part.diffHunks.forEach((hunk) => {
      if (hunk.oldCount > 0) {
        removedRanges.push({
          start: hunk.oldStart,
          end: hunk.oldStart + hunk.oldCount - 1
        });
      }
      if (hunk.newCount > 0) {
        addedRanges.push({
          start: hunk.newStart,
          end: hunk.newStart + hunk.newCount - 1
        });
      }
    });

    return { addedRanges, removedRanges };
  }

  if (
    part.diffLineMode === 'absolute' &&
    typeof part.diffLineOffset === 'number' &&
    Number.isInteger(part.diffLineOffset) &&
    part.diffLineOffset >= 0
  ) {
    const startLine = part.diffLineOffset + 1;
    const removed = Math.max(0, part.toolRemovedCount ?? 0);
    const added = Math.max(0, part.toolAddedCount ?? 0);

    if (removed > 0) {
      removedRanges.push({
        start: startLine,
        end: startLine + removed - 1
      });
    }
    if (added > 0) {
      addedRanges.push({
        start: startLine,
        end: startLine + added - 1
      });
    }
  }

  return { addedRanges, removedRanges };
};

const shouldResetFileChangeAggregation = (
  part: ToolPart,
  preciseRanges: ReturnType<typeof getPreciseRangesFromToolPart>
) => {
  if (part.toolName === 'write_file') return true;
  if (part.toolName === 'apply_patch') return false;

  const hasPreciseRanges =
    preciseRanges.addedRanges.length > 0 || preciseRanges.removedRanges.length > 0;
  if (hasPreciseRanges) return false;

  const added = Math.max(0, part.toolAddedCount ?? 0);
  const removed = Math.max(0, part.toolRemovedCount ?? 0);
  const oldValue = part.diffOldValue?.trim() ?? '';
  const newValue = part.diffNewValue?.trim() ?? '';

  if (!oldValue && newValue) return true;
  if (oldValue && !newValue) return true;
  if (added > 0 && removed > 0) return true;
  return false;
};

export const getUserTurns = (
  chatMessages: ThreadChatDisplayMessage[]
): ThreadChatUserTurn[] => {
  const turns: ThreadChatUserTurn[] = [];
  let previousUserIndex = -1;

  for (let index = 0; index < chatMessages.length; index += 1) {
    if (chatMessages[index]?.role !== 'user') continue;

    if (previousUserIndex >= 0) {
      turns.push({
        userIndex: previousUserIndex,
        endIndex: index - 1
      });
    }
    previousUserIndex = index;
  }

  if (previousUserIndex >= 0) {
    turns.push({
      userIndex: previousUserIndex,
      endIndex: chatMessages.length - 1
    });
  }

  return turns;
};

export const hasCompletedAssistantReplyInTurn = (
  chatMessages: ThreadChatDisplayMessage[],
  turn: ThreadChatUserTurn
) => {
  for (let index = turn.endIndex; index > turn.userIndex; index -= 1) {
    const message = chatMessages[index];
    if (!message || message.role !== 'assistant') continue;
    if (message.finishReason !== 'tool_calls') return true;
  }

  return false;
};

const collectFileChanges = (
  chatMessages: ThreadChatDisplayMessage[],
  sourceIndexOffset = 0
) => {
  const aggregated = new Map<string, AggregatedFileChange>();

  chatMessages.forEach((message, sourceIndex) => {
    message.parts.forEach((part) => {
      if (part.type !== 'tool') return;
      if (part.status !== 'success') return;
      if (!isFileDiffToolPart(part)) return;

      const filePath = normalizeFilePath(part.toolInvocation);
      if (!filePath) return;

      const added = Math.max(0, part.toolAddedCount ?? 0);
      const removed = Math.max(0, part.toolRemovedCount ?? 0);
      const preciseRanges = getPreciseRangesFromToolPart(part);
      const current = aggregated.get(filePath);
      const shouldReset = shouldResetFileChangeAggregation(part, preciseRanges);
      const baseline = shouldReset ? undefined : current;
      const shouldUseLatestApplyPatchVisual =
        part.toolName === 'apply_patch' && Boolean(baseline);
      const isMergedFromMultipleEdits =
        Boolean(baseline) && !shouldUseLatestApplyPatchVisual;
      const next: AggregatedFileChange = {
        id: baseline?.id ?? `${filePath}-${part.toolCallId}`,
        filePath,
        toolName: part.toolName,
        added: 0,
        removed: 0,
        netAdded: Math.max(0, part.toolNetAddedCount ?? added),
        netRemoved: Math.max(0, part.toolNetRemovedCount ?? removed),
        latestAdded: added,
        latestRemoved: removed,
        editCount: (baseline?.editCount ?? 0) + 1,
        lastSourceIndex: sourceIndexOffset + sourceIndex,
        diffOldValue: isMergedFromMultipleEdits
          ? concatDiffText(baseline?.diffOldValue, part.diffOldValue)
          : (part.diffOldValue ?? baseline?.diffOldValue ?? ''),
        diffNewValue: isMergedFromMultipleEdits
          ? concatDiffText(baseline?.diffNewValue, part.diffNewValue)
          : (part.diffNewValue ?? baseline?.diffNewValue ?? ''),
        diffLineOffset: isMergedFromMultipleEdits
          ? undefined
          : (part.diffLineOffset ?? baseline?.diffLineOffset),
        diffLineMode: isMergedFromMultipleEdits
          ? undefined
          : (part.diffLineMode ?? baseline?.diffLineMode),
        diffHunks: isMergedFromMultipleEdits
          ? undefined
          : (part.diffHunks ?? baseline?.diffHunks),
        preciseAddedRanges: mergeLineRanges([
          ...(baseline?.preciseAddedRanges ?? []),
          ...preciseRanges.addedRanges
        ]),
        preciseRemovedRanges: mergeLineRanges([
          ...(baseline?.preciseRemovedRanges ?? []),
          ...preciseRanges.removedRanges
        ]),
        fallbackAdded:
          (baseline?.fallbackAdded ?? 0) +
          (preciseRanges.addedRanges.length > 0 ? 0 : added),
        fallbackRemoved:
          (baseline?.fallbackRemoved ?? 0) +
          (preciseRanges.removedRanges.length > 0 ? 0 : removed)
      };
      next.added =
        getLineRangeSize(next.preciseAddedRanges) + next.fallbackAdded;
      next.removed =
        getLineRangeSize(next.preciseRemovedRanges) + next.fallbackRemoved;
      aggregated.set(filePath, next);
    });
  });

  return [...aggregated.values()]
    .map((change) => ({
      id: change.id,
      filePath: change.filePath,
      toolName: change.toolName,
      added: change.added,
      removed: change.removed,
      netAdded: change.netAdded,
      netRemoved: change.netRemoved,
      latestAdded: change.latestAdded,
      latestRemoved: change.latestRemoved,
      editCount: change.editCount,
      lastSourceIndex: change.lastSourceIndex,
      diffOldValue: change.diffOldValue,
      diffNewValue: change.diffNewValue,
      diffLineOffset: change.diffLineOffset,
      diffLineMode: change.diffLineMode,
      diffHunks: change.diffHunks
    }))
    .sort((left, right) => right.lastSourceIndex - left.lastSourceIndex);
};

export const getConversationFileChanges = (
  chatMessages: ThreadChatDisplayMessage[]
) => collectFileChanges(chatMessages);

export const getLatestTurnFileChanges = (
  chatMessages: ThreadChatDisplayMessage[]
) => {
  if (chatMessages.length === 0) return [];
  const turns = getUserTurns(chatMessages);
  const latestTurn = turns[turns.length - 1];
  if (!latestTurn || latestTurn.endIndex <= latestTurn.userIndex) return [];
  const turnMessages = chatMessages.slice(
    latestTurn.userIndex + 1,
    latestTurn.endIndex + 1
  );
  if (turnMessages.length === 0) return [];

  return collectFileChanges(turnMessages, latestTurn.userIndex + 1);
};

export const getTurnFileChangeSummaries = (
  chatMessages: ThreadChatDisplayMessage[]
) => {
  const cached = turnSummaryCache;
  if (cached?.messages === chatMessages) {
    return cached.value;
  }

  const turns = getUserTurns(chatMessages);
  const summaries: ThreadChatTurnFileChangeSummary[] = [];
  let startTurnIndex = 0;

  if (cached) {
    const stablePrefixLength = findStablePrefixLength(
      cached.messages,
      chatMessages
    );
    const reusableSummaries = cached.value.filter(
      (summary) => summary.endIndex < stablePrefixLength
    );
    summaries.push(...reusableSummaries);
    startTurnIndex = turns.findIndex(
      (turn) => turn.endIndex >= stablePrefixLength
    );
    if (startTurnIndex < 0) startTurnIndex = turns.length;
  }

  for (
    let turnIndex = startTurnIndex;
    turnIndex < turns.length;
    turnIndex += 1
  ) {
    const turn = turns[turnIndex];
    if (!turn) continue;
    if (turn.endIndex <= turn.userIndex) continue;
    const turnMessages = chatMessages.slice(
      turn.userIndex + 1,
      turn.endIndex + 1
    );
    if (turnMessages.length === 0) continue;
    const fileChanges = collectFileChanges(turnMessages, turn.userIndex + 1);
    if (fileChanges.length === 0) continue;

    summaries.push({
      id: `turn-file-change-${turn.userIndex}-${turn.endIndex}`,
      turnIndex: turnIndex + 1,
      userIndex: turn.userIndex,
      endIndex: turn.endIndex,
      fileChanges
    });
  }

  turnSummaryCache = {
    messages: chatMessages,
    value: summaries
  };
  return summaries;
};

export const getMessageRenderItems = (
  chatMessages: ThreadChatDisplayMessage[]
) => {
  const cached = renderItemsCache;
  if (cached?.messages === chatMessages) {
    return cached.value;
  }

  const items: MessageRenderItem[] = [];
  if (chatMessages.length === 0) return items;
  const turns = getUserTurns(chatMessages);

  if (turns.length === 0) {
    chatMessages.forEach((message, sourceIndex) => {
      if (!message) return;
      items.push({ type: 'message', sourceIndex, message });
    });
    return items;
  }

  const lastTurn = turns[turns.length - 1]!;
  // Worked 规则：
  // 1) 最新轮次始终不走 Worked，直接展开渲染（含流式中与流式结束后）；
  // 2) 其余历史轮次走 Worked 分组，默认折叠以减少 DOM。
  const expandedTurnUserIndex = lastTurn.userIndex;

  const renderTurnAsExpanded = (turn: ThreadChatUserTurn) => {
    for (let index = turn.userIndex; index <= turn.endIndex; index += 1) {
      const message = chatMessages[index];
      if (!message) continue;
      items.push({
        type: 'message',
        sourceIndex: index,
        message
      });
    }
  };

  const renderTurnAsCollapsed = (turn: ThreadChatUserTurn) => {
    const userMessage = chatMessages[turn.userIndex];
    if (userMessage) {
      items.push({
        type: 'message',
        sourceIndex: turn.userIndex,
        message: userMessage
      });
    }

    const assistantIndices: number[] = [];
    for (let index = turn.userIndex + 1; index <= turn.endIndex; index += 1) {
      if (chatMessages[index]?.role === 'assistant') {
        assistantIndices.push(index);
      }
    }

    const finalSummaryIndex = [...assistantIndices]
      .reverse()
      .find((index) => chatMessages[index]?.finishReason !== 'tool_calls');

    if (finalSummaryIndex == null) {
      const pendingChainMessages: ThreadChatDisplayMessage[] = [];
      for (let index = turn.userIndex + 1; index <= turn.endIndex; index += 1) {
        const message = chatMessages[index];
        if (!message || message.role === 'user') continue;
        pendingChainMessages.push(message);
      }

      if (pendingChainMessages.length > 0) {
        items.push({
          type: 'tool-group',
          sourceIndex: turn.userIndex + 1,
          id: `tool-group-${turn.userIndex}`,
          tools: pendingChainMessages,
          defaultOpen: false
        });
      }
      return;
    }

    const toolChainMessages: ThreadChatDisplayMessage[] = [];
    for (
      let index = turn.userIndex + 1;
      index < finalSummaryIndex;
      index += 1
    ) {
      const message = chatMessages[index];
      if (!message || message.role === 'user') continue;
      toolChainMessages.push(message);
    }

    if (toolChainMessages.length > 0) {
      const groupStartIndex = turn.userIndex + 1;
      items.push({
        type: 'tool-group',
        sourceIndex: groupStartIndex,
        id: `tool-group-${turn.userIndex}`,
        tools: toolChainMessages,
        defaultOpen: false
      });
    }

    for (let index = finalSummaryIndex; index <= turn.endIndex; index += 1) {
      const message = chatMessages[index];
      if (!message) continue;
      items.push({
        type: 'message',
        sourceIndex: index,
        message
      });
    }
  };

  let cursor = 0;
  turns.forEach((turn) => {
    while (cursor < turn.userIndex) {
      const message = chatMessages[cursor];
      if (message) {
        items.push({
          type: 'message',
          sourceIndex: cursor,
          message
        });
      }
      cursor += 1;
    }

    if (turn.userIndex === expandedTurnUserIndex) {
      renderTurnAsExpanded(turn);
    } else {
      renderTurnAsCollapsed(turn);
    }

    cursor = turn.endIndex + 1;
  });

  while (cursor < chatMessages.length) {
    const message = chatMessages[cursor];
    if (message) {
      items.push({
        type: 'message',
        sourceIndex: cursor,
        message
      });
    }
    cursor += 1;
  }

  renderItemsCache = {
    messages: chatMessages,
    value: items
  };
  return items;
};

const isToolRunningMessage = (message: ThreadChatDisplayMessage) =>
  message.role === 'tool' &&
  message.parts.some(
    (part) => part.type === 'tool' && part.status === 'running'
  );

const isToolRelatedMessage = (message: ThreadChatDisplayMessage) =>
  message.role === 'tool' ||
  (message.role === 'assistant' && message.finishReason === 'tool_calls');

export const getWorkedDividerSourceIndex = (
  chatMessages: ThreadChatDisplayMessage[],
  isLoading: boolean
) => {
  if (isLoading || chatMessages.length === 0) return -1;

  let lastUserIndex = -1;
  for (let index = chatMessages.length - 1; index >= 0; index -= 1) {
    if (chatMessages[index]?.role === 'user') {
      lastUserIndex = index;
      break;
    }
  }
  if (lastUserIndex < 0 || lastUserIndex >= chatMessages.length - 1) return -1;

  const turnMessages = chatMessages.slice(lastUserIndex + 1);
  const hasAnyToolMessage = turnMessages.some((message) => message.role === 'tool');
  if (!hasAnyToolMessage) return -1;

  const hasRunningTool = turnMessages.some(isToolRunningMessage);
  if (hasRunningTool) return -1;

  let lastToolRelatedIndex = -1;
  for (let offset = 0; offset < turnMessages.length; offset += 1) {
    if (isToolRelatedMessage(turnMessages[offset])) {
      lastToolRelatedIndex = offset;
    }
  }
  if (lastToolRelatedIndex < 0) return -1;

  for (
    let offset = lastToolRelatedIndex + 1;
    offset < turnMessages.length;
    offset += 1
  ) {
    const message = turnMessages[offset];
    if (
      message?.role === 'assistant' &&
      message.finishReason !== 'tool_calls'
    ) {
      return lastUserIndex + 1 + offset;
    }
  }

  return -1;
};
