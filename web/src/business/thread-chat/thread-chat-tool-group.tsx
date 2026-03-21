import { memo, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ChevronDown } from 'lucide-react';
import { Shimmer } from '@/components/ai-elements/shimmer';
import { Task, TaskTrigger } from '@/components/ai-elements/task';
import { ThreadChatMessageItem } from '@/business/thread-chat/thread-chat-message-item';
import {
  getConversationFileChanges,
  shouldIgnoreToolDiffStats,
  type CopyMeta
} from '@/business/thread-chat/thread-chat-message-utils';
import {
  type ThreadChatDisplayMessage,
  type ThreadChatPart
} from '@/business/thread-chat/types';
import { useStickToBottomContext } from 'use-stick-to-bottom';

type ThreadChatToolGroupProps = {
  groupId: string;
  tools: ThreadChatDisplayMessage[];
  defaultOpen?: boolean;
  isExecuting?: boolean;
};

const EDIT_TOOL_NAMES = new Set(['apply_patch', 'edit_file', 'write_file']);
export const EMPTY_COPY_META: CopyMeta = { canCopy: false, copyText: '' };
const TOOL_GROUP_TITLE = '执行过程';

const getToolPart = (message: ThreadChatDisplayMessage) =>
  message.parts.find(
    (part): part is Extract<ThreadChatPart, { type: 'tool' }> =>
      part.type === 'tool'
  );

const normalizeFilePaths = (toolInvocation?: string) =>
  (toolInvocation ?? '')
    .split(',')
    .map((path) => path.trim())
    .filter(Boolean);

const buildMergedToolInvocation = (filePaths: string[]) => {
  if (filePaths.length <= 1) return filePaths[0] ?? '文件';
  return `${filePaths.length} 个文件`;
};

const buildMergedToolDiffValues = (messages: ThreadChatDisplayMessage[]) => {
  const oldSections: string[] = [];
  const newSections: string[] = [];

  messages.forEach((message) => {
    const toolPart = getToolPart(message);
    if (!toolPart) return;
    if (shouldIgnoreToolDiffStats(toolPart)) return;

    if (toolPart.diffOldValue?.trim()) {
      oldSections.push(toolPart.diffOldValue);
    }
    if (toolPart.diffNewValue?.trim()) {
      newSections.push(toolPart.diffNewValue);
    }
  });

  return {
    oldValue: oldSections.join('\n\n'),
    newValue: newSections.join('\n\n')
  };
};

const buildMergedDiffSections = (messages: ThreadChatDisplayMessage[]) =>
  messages.flatMap((message, index) => {
    const toolPart = getToolPart(message);
    if (!toolPart) return [];
    if (shouldIgnoreToolDiffStats(toolPart)) return [];

    const hasDiffContent =
      Boolean(toolPart.diffOldValue?.trim()) ||
      Boolean(toolPart.diffNewValue?.trim());
    if (!hasDiffContent) return [];

    return [
      {
        id: `${message.id}-${toolPart.toolCallId ?? index}`,
        filePath: toolPart.toolInvocation,
        oldValue: toolPart.diffOldValue,
        newValue: toolPart.diffNewValue,
        diffLineOffset: toolPart.diffLineOffset,
        diffLineMode: toolPart.diffLineMode,
        diffHunks: toolPart.diffHunks
      }
    ];
  });

export const getEditSessionTargetKey = (
  message: ThreadChatDisplayMessage
): string | null => {
  if (message.role !== 'tool') return null;
  const toolPart = getToolPart(message);
  if (!toolPart || !EDIT_TOOL_NAMES.has(toolPart.toolName)) return null;

  const filePaths = normalizeFilePaths(toolPart.toolInvocation);
  if (filePaths.length === 0) return null;

  return `${toolPart.toolName}:${[...filePaths].sort().join('|')}`;
};

const mergeToolMessages = (
  tools: ThreadChatDisplayMessage[]
): ThreadChatDisplayMessage[] => {
  const items: ThreadChatDisplayMessage[] = [];

  for (let index = 0; index < tools.length; index += 1) {
    const currentMessage = tools[index];
    if (!currentMessage) continue;

    const targetKey = getEditSessionTargetKey(currentMessage);
    if (!targetKey) {
      items.push(currentMessage);
      continue;
    }

    const currentToolPart = getToolPart(currentMessage);
    if (!currentToolPart) {
      items.push(currentMessage);
      continue;
    }

    const groupedMessages = [currentMessage];
    let nextIndex = index + 1;
    while (nextIndex < tools.length) {
      const nextMessage = tools[nextIndex];
      if (!nextMessage) break;
      if (getEditSessionTargetKey(nextMessage) !== targetKey) break;
      groupedMessages.push(nextMessage);
      nextIndex += 1;
    }

    if (groupedMessages.length === 1) {
      items.push(currentMessage);
      continue;
    }

    const filePaths = normalizeFilePaths(currentToolPart.toolInvocation);
    const isExecuting = groupedMessages.some((message) => {
      const toolPart = getToolPart(message);
      return toolPart?.status === 'running';
    });
    const mergedDiffValues = buildMergedToolDiffValues(groupedMessages);
    const mergedDiffSections = buildMergedDiffSections(groupedMessages);
    const aggregatedFileChange = getConversationFileChanges(groupedMessages)[0];

    items.push({
      id: `merged-tool-${groupedMessages[0]?.id ?? index}`,
      role: 'tool',
      parts: [
        {
          id: `merged-tool-${groupedMessages[0]?.id ?? index}-part`,
          type: 'tool',
          toolName: currentToolPart.toolName,
          toolInvocation: buildMergedToolInvocation(filePaths),
          toolAddedCount: aggregatedFileChange?.added,
          toolRemovedCount: aggregatedFileChange?.removed,
          toolNetAddedCount: aggregatedFileChange?.netAdded,
          toolNetRemovedCount: aggregatedFileChange?.netRemoved,
          toolCallId: currentToolPart.toolCallId,
          status: isExecuting
            ? 'running'
            : groupedMessages.some(
                  (message) => getToolPart(message)?.status === 'error'
                )
              ? 'error'
              : 'success',
          content: '',
          contentFormat: 'diff',
          diffOldValue: mergedDiffValues.oldValue,
          diffNewValue: mergedDiffValues.newValue,
          diffSections: mergedDiffSections
        }
      ]
    });
    index = nextIndex - 1;
  }

  return items;
};

export const mergeSequentialEditToolMessages = mergeToolMessages;

export const ThreadChatToolGroup = memo(
  ({
    groupId,
    tools,
    defaultOpen = false,
    isExecuting = false
  }: ThreadChatToolGroupProps) => {
    const { stopScroll } = useStickToBottomContext();
    const reduceMotion = useReducedMotion();
    const [open, setOpen] = useState(defaultOpen);
    const [shouldRenderExpandedContent, setShouldRenderExpandedContent] =
      useState(defaultOpen);
    const mergedTools = useMemo(() => {
      if (!shouldRenderExpandedContent) return [];
      return mergeToolMessages(tools);
    }, [shouldRenderExpandedContent, tools]);

    useEffect(() => {
      setOpen(defaultOpen);
      setShouldRenderExpandedContent(defaultOpen);
    }, [defaultOpen, groupId]);

    const handleOpenChange = (nextOpen: boolean) => {
      stopScroll();
      setOpen(nextOpen);
      if (!nextOpen || shouldRenderExpandedContent) return;
      setShouldRenderExpandedContent(true);
    };
    const shouldShowExpandedContent =
      open && shouldRenderExpandedContent && mergedTools.length > 0;

    return (
      <div>
        <Task className="w-full" onOpenChange={handleOpenChange} open={open}>
          <TaskTrigger className="w-full" title={TOOL_GROUP_TITLE}>
            {(() => {
              const content = (
                <div className="my-2 flex w-full flex-col gap-2 text-xs text-muted-foreground">
                  <div className="flex w-full items-center gap-3">
                    <div className="h-px flex-1 bg-border" />
                    <div className="inline-flex shrink-0 items-center gap-2 font-medium">
                      <span>{TOOL_GROUP_TITLE}</span>
                      <ChevronDown className="size-3.5 opacity-70 transition-all group-data-[state=open]:rotate-180 group-data-[state=open]:opacity-100" />
                    </div>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                </div>
              );

              if (isExecuting) {
                return <Shimmer className="block w-full">{content}</Shimmer>;
              }

              return content;
            })()}
          </TaskTrigger>
          <AnimatePresence initial={false}>
            {shouldShowExpandedContent ? (
              <motion.div
                animate={{ opacity: 1, y: 0 }}
                className="overflow-hidden"
                exit={{ opacity: 0, y: -4 }}
                initial={{ opacity: 0, y: -4 }}
                key={`${groupId}-content`}
                transition={
                  reduceMotion
                    ? { duration: 0 }
                    : {
                        opacity: {
                          duration: open ? 0.18 : 0.14,
                          ease: 'easeOut'
                        },
                        y: {
                          duration: open ? 0.18 : 0.14,
                          ease: [0.22, 1, 0.36, 1]
                        }
                      }
                }
              >
                <div className="mt-4 space-y-2 border-muted border-l-2 pl-4">
                  <div className="space-y-3">
                    {mergedTools.map((message) => (
                      <ThreadChatMessageItem
                        copyMeta={EMPTY_COPY_META}
                        isCurrentStreaming={false}
                        key={message.id}
                        message={message}
                      />
                    ))}
                  </div>
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </Task>
      </div>
    );
  },
  (prevProps, nextProps) => {
    if (prevProps.groupId !== nextProps.groupId) return false;
    if (prevProps.defaultOpen !== nextProps.defaultOpen) return false;
    if (prevProps.tools === nextProps.tools) return true;
    if (prevProps.isExecuting !== nextProps.isExecuting) return false;
    if (prevProps.tools.length !== nextProps.tools.length) return false;
    for (let index = 0; index < prevProps.tools.length; index += 1) {
      if (prevProps.tools[index] !== nextProps.tools[index]) return false;
    }
    return true;
  }
);

ThreadChatToolGroup.displayName = 'ThreadChatToolGroup';
