import {
  memo,
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton
} from '@/components/ai-elements/conversation';
import { Loader } from '@/components/ai-elements/loader';
import { Shimmer } from '@/components/ai-elements/shimmer';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle
} from '@/components/ui/empty';
import { cn } from '@/lib/utils';
import { ThreadChatFileChangeSummary } from '@/business/thread-chat/thread-chat-file-change-summary';
import { ThreadChatMessageItem } from '@/business/thread-chat/thread-chat-message-item';
import {
  getEditSessionTargetKey,
  mergeSequentialEditToolMessages,
  ThreadChatToolGroup
} from '@/business/thread-chat/thread-chat-tool-group';
import {
  getCopyMetaList,
  getMessageRenderItems,
  hasCompletedAssistantReplyInTurn,
  getUserTurns,
  getTurnFileChangeSummaries,
  type ThreadChatTurnFileChangeSummary
} from '@/business/thread-chat/thread-chat-message-utils';
import {
  type ThreadChatDisplayMessage,
  type ThreadChatPart,
  type ThreadChatStatus
} from '@/business/thread-chat/types';
import { useStickToBottomContext } from 'use-stick-to-bottom';

type ThreadChatMessageListProps = {
  threadId?: string;
  chatMessages: ThreadChatDisplayMessage[];
  streamErrorMessage?: string;
  hasTurnFailureMessages?: boolean;
  isLoading: boolean;
  isInitializing: boolean;
  isThinking: boolean;
  chatStatus: ThreadChatStatus;
  immediateResponding?: boolean;
  onResetEnvironmentInitialization?: () => void | Promise<void>;
  isEnvironmentResetting?: boolean;
  emptyTitle: string;
  emptyDescription?: string;
  emptyMedia?: ReactNode;
  conversationContentClassName?: string;
};

const MAX_RENDER_ITEMS_WHILE_LOADING = 120;
const DEFAULT_VISIBLE_TURN_COUNT = 12;
const LOAD_MORE_TURN_COUNT = 12;
const EMPTY_COPY_META = { canCopy: false, copyText: '' } as const;

const hasRunningToolPart = (message: ThreadChatDisplayMessage) =>
  message.role === 'tool' &&
  message.parts.some(
    (part): part is Extract<ThreadChatPart, { type: 'tool' }> =>
      part.type === 'tool' && part.status === 'running'
  );

function ThreadChatInitialAutoScroll({
  enabled,
  threadId
}: {
  enabled: boolean;
  threadId?: string;
}) {
  const { scrollToBottom } = useStickToBottomContext();
  const autoScrolledThreadRef = useRef<string | null>(null);

  useEffect(() => {
    const scopeKey = threadId?.trim() || '__default__';
    if (!enabled) {
      if (threadId) autoScrolledThreadRef.current = null;
      return;
    }
    if (autoScrolledThreadRef.current === scopeKey) return;
    autoScrolledThreadRef.current = scopeKey;

    if (typeof window === 'undefined') {
      void scrollToBottom('instant');
      return;
    }

    let raf1 = 0;
    let raf2 = 0;
    raf1 = window.requestAnimationFrame(() => {
      raf2 = window.requestAnimationFrame(() => {
        void scrollToBottom('instant');
      });
    });

    return () => {
      window.cancelAnimationFrame(raf1);
      window.cancelAnimationFrame(raf2);
    };
  }, [enabled, scrollToBottom, threadId]);

  return null;
}

function ThreadChatAutoScrollOnUserSubmit({
  threadId,
  tailMessageId,
  tailMessageRole
}: {
  threadId?: string;
  tailMessageId: string | null;
  tailMessageRole?: ThreadChatDisplayMessage['role'];
}) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();
  const previousTailMessageIdRef = useRef<string | null>(tailMessageId);
  const wasAtBottomRef = useRef(isAtBottom);

  useEffect(() => {
    wasAtBottomRef.current = isAtBottom;
  }, [isAtBottom]);

  useEffect(() => {
    previousTailMessageIdRef.current = null;
    wasAtBottomRef.current = isAtBottom;
  }, [threadId, isAtBottom]);

  useEffect(() => {
    const previousTailMessageId = previousTailMessageIdRef.current;
    const hasTailMessageChanged = tailMessageId !== previousTailMessageId;
    const shouldStickToBottom =
      hasTailMessageChanged &&
      tailMessageRole === 'user' &&
      wasAtBottomRef.current;

    previousTailMessageIdRef.current = tailMessageId;

    if (!shouldStickToBottom) return;

    if (typeof window === 'undefined') {
      void scrollToBottom('instant');
      return;
    }

    let raf1 = 0;
    let raf2 = 0;
    raf1 = window.requestAnimationFrame(() => {
      raf2 = window.requestAnimationFrame(() => {
        void scrollToBottom('instant');
      });
    });

    return () => {
      window.cancelAnimationFrame(raf1);
      window.cancelAnimationFrame(raf2);
    };
  }, [scrollToBottom, tailMessageId, tailMessageRole]);

  return null;
}

function ThreadChatRespondingStickController({
  isResponding
}: {
  isResponding: boolean;
}) {
  const { isAtBottom, scrollToBottom, state, stopScroll } =
    useStickToBottomContext();
  const previousRespondingRef = useRef(isResponding);
  const shouldReleaseStickRef = useRef(false);

  useEffect(() => {
    const wasResponding = previousRespondingRef.current;
    previousRespondingRef.current = isResponding;

    if (!wasResponding && isResponding) {
      const shouldStickToBottom = isAtBottom || state.isNearBottom;
      shouldReleaseStickRef.current = shouldStickToBottom;
      if (!shouldStickToBottom) return;
      void scrollToBottom('instant');
      return;
    }

    if (wasResponding && !isResponding && shouldReleaseStickRef.current) {
      // 流式阶段需要底部锁来持续跟随增量内容；静态阶段则主动释放，
      // 避免历史消息展开/收起继续被 ResizeObserver 当成“应自动置底”的事件。
      stopScroll();
      shouldReleaseStickRef.current = false;
    }
  }, [isAtBottom, isResponding, scrollToBottom, state, stopScroll]);

  return null;
}

function ThreadChatLoadMoreTurnsControl({
  hiddenTurnCount,
  onLoadMoreTurns,
  visibleTurnCount
}: {
  hiddenTurnCount: number;
  onLoadMoreTurns: () => void;
  visibleTurnCount: number;
}) {
  const { scrollRef, stopScroll } = useStickToBottomContext();
  const pendingLoadMoreScrollHeightRef = useRef<number | null>(null);

  useLayoutEffect(() => {
    const previousScrollHeight = pendingLoadMoreScrollHeightRef.current;
    if (previousScrollHeight == null) return;

    const scrollElement = scrollRef.current;
    pendingLoadMoreScrollHeightRef.current = null;
    if (!scrollElement) return;

    const scrollDelta = scrollElement.scrollHeight - previousScrollHeight;
    if (scrollDelta > 0) {
      scrollElement.scrollTop += scrollDelta;
    }
  }, [scrollRef, visibleTurnCount]);

  if (hiddenTurnCount <= 0) return null;

  return (
    <div className="flex justify-center">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          const scrollElement = scrollRef.current;
          pendingLoadMoreScrollHeightRef.current =
            scrollElement?.scrollHeight ?? null;
          stopScroll();
          onLoadMoreTurns();
        }}
      >
        加载更早的 {Math.min(hiddenTurnCount, LOAD_MORE_TURN_COUNT)} 轮消息
      </Button>
    </div>
  );
}

const ThreadChatFileChangeSummaryGroup = memo(
  ({ summaries }: { summaries: ThreadChatTurnFileChangeSummary[] }) => (
    <>
      {summaries.map((summary) => (
        <ThreadChatFileChangeSummary
          fileChanges={summary.fileChanges}
          key={summary.id}
        />
      ))}
    </>
  ),
  (prevProps, nextProps) => prevProps.summaries === nextProps.summaries
);

ThreadChatFileChangeSummaryGroup.displayName =
  'ThreadChatFileChangeSummaryGroup';

const ThreadChatMessageRow = memo(
  ({
    copyMeta,
    disableCopy,
    isEnvironmentResetting,
    isCurrentStreaming,
    isLatestResponding,
    isThinking,
    message,
    onResetEnvironmentInitialization
  }: {
    copyMeta: ReturnType<typeof getCopyMetaList>[number];
    disableCopy: boolean;
    isEnvironmentResetting: boolean;
    isCurrentStreaming: boolean;
    isLatestResponding: boolean;
    isThinking: boolean;
    message: ThreadChatDisplayMessage;
    onResetEnvironmentInitialization?: () => void | Promise<void>;
  }) => {
    return (
      <ThreadChatMessageItem
        copyMeta={copyMeta}
        compactToolView={false}
        disableCopy={disableCopy}
        isEnvironmentResetting={isEnvironmentResetting}
        message={message}
        onResetEnvironmentInitialization={onResetEnvironmentInitialization}
        isCurrentStreaming={isCurrentStreaming}
        isThinking={isThinking}
        isLatestResponding={isLatestResponding}
      />
    );
  },
  (prevProps, nextProps) =>
    prevProps.message === nextProps.message &&
    prevProps.copyMeta === nextProps.copyMeta &&
    prevProps.disableCopy === nextProps.disableCopy &&
    prevProps.isCurrentStreaming === nextProps.isCurrentStreaming &&
    prevProps.isLatestResponding === nextProps.isLatestResponding &&
    prevProps.isThinking === nextProps.isThinking &&
    prevProps.isEnvironmentResetting === nextProps.isEnvironmentResetting &&
    prevProps.onResetEnvironmentInitialization ===
      nextProps.onResetEnvironmentInitialization
);

ThreadChatMessageRow.displayName = 'ThreadChatMessageRow';

const ThreadChatMergedEditSessionRow = memo(
  ({ messages }: { messages: ThreadChatDisplayMessage[] }) => (
    <>
      {messages.map((mergedMessage) => (
        <ThreadChatMessageItem
          copyMeta={EMPTY_COPY_META}
          compactToolView={false}
          disableCopy={false}
          isCurrentStreaming={false}
          key={mergedMessage.id}
          message={mergedMessage}
        />
      ))}
    </>
  ),
  (prevProps, nextProps) => prevProps.messages === nextProps.messages
);

ThreadChatMergedEditSessionRow.displayName = 'ThreadChatMergedEditSessionRow';

export const ThreadChatMessageList = memo(
  ({
    threadId,
    chatMessages,
    streamErrorMessage,
    hasTurnFailureMessages = false,
    isInitializing,
    isThinking,
    chatStatus,
    immediateResponding = false,
    onResetEnvironmentInitialization,
    isEnvironmentResetting = false,
    emptyTitle,
    emptyDescription,
    emptyMedia,
    conversationContentClassName
  }: ThreadChatMessageListProps) => {
    const shouldShowEmpty = chatMessages.length === 0 && !isInitializing;
    const shouldShowInitializing = chatMessages.length === 0 && isInitializing;
    const shouldShowStreamError =
      chatStatus === 'error' &&
      !hasTurnFailureMessages &&
      Boolean(streamErrorMessage && streamErrorMessage.trim().length > 0);
    const shouldAutoScrollOnInitialRender =
      !isInitializing && chatMessages.length > 0;
    const isResponding =
      chatStatus === 'submitted' ||
      chatStatus === 'streaming' ||
      immediateResponding;
    const copyMetaList = useMemo(
      () => getCopyMetaList(chatMessages),
      [chatMessages]
    );
    const lastUserIndex = useMemo(() => {
      for (let index = chatMessages.length - 1; index >= 0; index -= 1) {
        if (chatMessages[index]?.role === 'user') return index;
      }
      return -1;
    }, [chatMessages]);
    const renderItems = useMemo(
      () => getMessageRenderItems(chatMessages),
      [chatMessages]
    );
    const userTurns = useMemo(() => getUserTurns(chatMessages), [chatMessages]);
    const latestTurnHasCompletedAssistantReply = useMemo(() => {
      const latestTurn = userTurns[userTurns.length - 1];
      if (!latestTurn) return true;
      return hasCompletedAssistantReplyInTurn(chatMessages, latestTurn);
    }, [chatMessages, userTurns]);
    const [visibleTurnCount, setVisibleTurnCount] = useState(
      DEFAULT_VISIBLE_TURN_COUNT
    );
    const turnFileChangeSummaries = useMemo(
      () => getTurnFileChangeSummaries(chatMessages),
      [chatMessages]
    );
    useEffect(() => {
      setVisibleTurnCount(DEFAULT_VISIBLE_TURN_COUNT);
    }, [threadId]);

    useEffect(() => {
      if (userTurns.length <= visibleTurnCount) return;
      if (visibleTurnCount >= DEFAULT_VISIBLE_TURN_COUNT) return;
      setVisibleTurnCount(
        Math.min(DEFAULT_VISIBLE_TURN_COUNT, userTurns.length)
      );
    }, [userTurns.length, visibleTurnCount]);

    const hiddenTurnCount = Math.max(0, userTurns.length - visibleTurnCount);
    const firstVisibleTurn =
      hiddenTurnCount > 0 ? userTurns[hiddenTurnCount] : undefined;
    const firstVisibleSourceIndex = firstVisibleTurn?.userIndex ?? 0;
    const visibleTurnFileChangeSummaries = useMemo(() => {
      if (latestTurnHasCompletedAssistantReply && !isResponding) {
        return turnFileChangeSummaries;
      }

      // 当前轮只有在最终 assistant 总结落位后才允许插入文件摘要，
      // 避免流式工具链尚未结束时卡片提前挂到中间工具消息下方。
      return turnFileChangeSummaries.filter(
        (summary) => summary.userIndex !== lastUserIndex
      );
    }, [
      isResponding,
      lastUserIndex,
      latestTurnHasCompletedAssistantReply,
      turnFileChangeSummaries
    ]);
    const visibleStartIndex = useMemo(() => {
      if (!isResponding) return 0;
      return Math.max(0, renderItems.length - MAX_RENDER_ITEMS_WHILE_LOADING);
    }, [isResponding, renderItems.length]);
    const hiddenRenderItemCount = useMemo(
      () =>
        renderItems.reduce((count, item, index) => {
          if (index < visibleStartIndex) return count + 1;
          if (item.sourceIndex < firstVisibleSourceIndex) return count + 1;
          return count;
        }, 0),
      [firstVisibleSourceIndex, renderItems, visibleStartIndex]
    );
    const visibleRenderItems = useMemo(
      () =>
        renderItems.filter(
          (item, index) =>
            index >= visibleStartIndex &&
            item.sourceIndex >= firstVisibleSourceIndex
        ),
      [firstVisibleSourceIndex, renderItems, visibleStartIndex]
    );
    const turnSummaryInsertions = useMemo(() => {
      if (visibleTurnFileChangeSummaries.length === 0) {
        return new Map<number, ThreadChatTurnFileChangeSummary[]>();
      }

      const insertionMap = new Map<number, ThreadChatTurnFileChangeSummary[]>();
      visibleTurnFileChangeSummaries.forEach((summary) => {
        let lastRenderIndex = -1;
        for (
          let renderIndex = 0;
          renderIndex < visibleRenderItems.length;
          renderIndex += 1
        ) {
          const item = visibleRenderItems[renderIndex];
          if (
            item.sourceIndex >= summary.userIndex &&
            item.sourceIndex <= summary.endIndex
          ) {
            lastRenderIndex = renderIndex;
          }
        }
        if (lastRenderIndex < 0) return;
        const current = insertionMap.get(lastRenderIndex) ?? [];
        insertionMap.set(lastRenderIndex, [...current, summary]);
      });

      return insertionMap;
    }, [visibleTurnFileChangeSummaries, visibleRenderItems]);
    const isAwaitingFirstReply =
      isResponding &&
      lastUserIndex >= 0 &&
      lastUserIndex === chatMessages.length - 1;
    const tailMessage = chatMessages[chatMessages.length - 1];
    const handleLoadMoreTurns = () =>
      setVisibleTurnCount((current) =>
        Math.min(userTurns.length, current + LOAD_MORE_TURN_COUNT)
      );

    return (
      <Conversation className="h-full">
        <ConversationContent
          className={cn(
            'mx-auto w-full gap-4 max-w-3xl px-4 py-4 md:px-6',
            conversationContentClassName
          )}
        >
          <ThreadChatInitialAutoScroll
            enabled={shouldAutoScrollOnInitialRender}
            threadId={threadId}
          />
          <ThreadChatRespondingStickController isResponding={isResponding} />
          <ThreadChatAutoScrollOnUserSubmit
            threadId={threadId}
            tailMessageId={tailMessage?.id ?? null}
            tailMessageRole={tailMessage?.role}
          />
          <ThreadChatLoadMoreTurnsControl
            hiddenTurnCount={hiddenTurnCount}
            onLoadMoreTurns={handleLoadMoreTurns}
            visibleTurnCount={visibleTurnCount}
          />
          {shouldShowInitializing ? (
            <div className="flex h-full min-h-48 items-center justify-center">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader size={16} />
                <span>正在加载会话...</span>
              </div>
            </div>
          ) : shouldShowEmpty && !shouldShowStreamError ? (
            <Empty className="h-full border-0">
              <EmptyHeader>
                {emptyMedia}
                <EmptyTitle>{emptyTitle}</EmptyTitle>
                {emptyDescription && (
                  <EmptyDescription>{emptyDescription}</EmptyDescription>
                )}
              </EmptyHeader>
            </Empty>
          ) : (
            <>
              {isResponding && hiddenRenderItemCount > 0 && (
                <div className="rounded-md border bg-muted/30 px-3 py-2 text-center text-xs text-muted-foreground">
                  为提升流式性能，已暂时折叠 {hiddenRenderItemCount} 条较早消息
                </div>
              )}
              {(() => {
                const renderedItems: ReactNode[] = [];

                for (
                  let renderIndex = 0;
                  renderIndex < visibleRenderItems.length;
                  renderIndex += 1
                ) {
                  const item = visibleRenderItems[renderIndex];
                  if (!item) continue;

                  if (item.type === 'tool-group') {
                    const trailingSummaries =
                      turnSummaryInsertions.get(renderIndex) ?? [];
                    const isExecutingToolGroup =
                      item.tools.some(hasRunningToolPart);
                    renderedItems.push(
                      <div className="space-y-3" key={item.id}>
                        <ThreadChatToolGroup
                          defaultOpen={item.defaultOpen}
                          groupId={item.id}
                          tools={item.tools}
                          isExecuting={isExecutingToolGroup}
                        />
                        {trailingSummaries.map((summary) => (
                          <ThreadChatFileChangeSummary
                            fileChanges={summary.fileChanges}
                            key={summary.id}
                          />
                        ))}
                      </div>
                    );
                    continue;
                  }

                  const message = item.message;
                  const sourceIndex = item.sourceIndex;
                  const editSessionTargetKey =
                    sourceIndex > lastUserIndex
                      ? getEditSessionTargetKey(message)
                      : null;

                  if (editSessionTargetKey) {
                    const groupedMessages: ThreadChatDisplayMessage[] = [
                      message
                    ];
                    let groupEndIndex = renderIndex;

                    while (groupEndIndex + 1 < visibleRenderItems.length) {
                      const nextItem = visibleRenderItems[groupEndIndex + 1];
                      if (nextItem?.type !== 'message') break;
                      if (nextItem.sourceIndex <= lastUserIndex) break;
                      if (
                        getEditSessionTargetKey(nextItem.message) !==
                        editSessionTargetKey
                      ) {
                        break;
                      }
                      groupedMessages.push(nextItem.message);
                      groupEndIndex += 1;
                    }

                    if (groupedMessages.length > 1) {
                      const trailingSummaries =
                        turnSummaryInsertions.get(groupEndIndex) ?? [];
                      const mergedMessages =
                        mergeSequentialEditToolMessages(groupedMessages);

                      if (mergedMessages.length > 0) {
                        renderedItems.push(
                          <div
                            className="space-y-3"
                            key={`current-edit-session-${groupedMessages[0]?.id ?? renderIndex}`}
                          >
                            <ThreadChatMergedEditSessionRow
                              messages={mergedMessages}
                            />
                            <ThreadChatFileChangeSummaryGroup
                              summaries={trailingSummaries}
                            />
                          </div>
                        );
                        renderIndex = groupEndIndex;
                        continue;
                      }
                    }
                  }

                  const trailingSummaries =
                    turnSummaryInsertions.get(renderIndex) ?? [];
                  const isLastMessage = sourceIndex === chatMessages.length - 1;
                  const isCurrentStreaming =
                    isResponding &&
                    isLastMessage &&
                    message.role === 'assistant';
                  const isLatestResponding =
                    isResponding && isLastMessage && message.role !== 'user';
                  const disableCopy =
                    isLatestResponding &&
                    message.role === 'assistant' &&
                    sourceIndex > lastUserIndex;
                  const rowIsThinking = isLatestResponding && isThinking;
                  renderedItems.push(
                    <div className="space-y-3" key={message.id}>
                      <ThreadChatMessageRow
                        copyMeta={copyMetaList[sourceIndex] ?? EMPTY_COPY_META}
                        disableCopy={disableCopy}
                        isEnvironmentResetting={isEnvironmentResetting}
                        isCurrentStreaming={isCurrentStreaming}
                        isLatestResponding={isLatestResponding}
                        isThinking={rowIsThinking}
                        message={message}
                        onResetEnvironmentInitialization={
                          onResetEnvironmentInitialization
                        }
                      />
                      <ThreadChatFileChangeSummaryGroup
                        summaries={trailingSummaries}
                      />
                    </div>
                  );
                }

                return renderedItems;
              })()}
              {shouldShowStreamError && (
                <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  <div className="font-medium">消息流发生异常</div>
                  <div className="mt-1 whitespace-pre-wrap wrap-break-word text-destructive/90">
                    {streamErrorMessage}
                  </div>
                </div>
              )}
              {isAwaitingFirstReply && (
                <div className="inline-flex max-w-max items-center gap-2 rounded-md px-1 text-sm text-muted-foreground">
                  <Shimmer>正在回复...</Shimmer>
                </div>
              )}
            </>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
    );
  },
  (prevProps, nextProps) =>
    prevProps.chatMessages === nextProps.chatMessages &&
    prevProps.streamErrorMessage === nextProps.streamErrorMessage &&
    prevProps.hasTurnFailureMessages === nextProps.hasTurnFailureMessages &&
    prevProps.isLoading === nextProps.isLoading &&
    prevProps.isInitializing === nextProps.isInitializing &&
    prevProps.isThinking === nextProps.isThinking &&
    prevProps.chatStatus === nextProps.chatStatus &&
    prevProps.immediateResponding === nextProps.immediateResponding &&
    prevProps.onResetEnvironmentInitialization ===
      nextProps.onResetEnvironmentInitialization &&
    prevProps.isEnvironmentResetting === nextProps.isEnvironmentResetting &&
    prevProps.emptyTitle === nextProps.emptyTitle &&
    prevProps.emptyDescription === nextProps.emptyDescription &&
    prevProps.emptyMedia === nextProps.emptyMedia &&
    prevProps.conversationContentClassName ===
      nextProps.conversationContentClassName
);

ThreadChatMessageList.displayName = 'ThreadChatMessageList';
