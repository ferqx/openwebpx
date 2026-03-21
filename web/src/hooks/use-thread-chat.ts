import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { type Message as LangGraphMessage } from "@langchain/langgraph-sdk";
import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import {
  type ThreadChatDisplayMessage,
  type ThreadChatStatus,
  type ThreadChatTokenUsageSummary,
} from "@/business/thread-chat/types";
import { type StreamContextType } from "@/provider/stream";
import {
  buildEnvironmentInitOutput,
  buildEnvironmentInitTitle,
  buildTokenUsageSummaryFromMessages,
  clearStabilizedThreadMessages,
  getErrorMessageText,
  normalizeThreadChatMessages,
} from "@/hooks/thread-chat-utils";
import { useThreadEnvironmentBootstrap } from "@/hooks/use-thread-environment-bootstrap";
import {
  type FailedTurnRecord,
  useThreadChatTurnState,
} from "@/hooks/use-thread-chat-turn-state";
import { getOptimisticUserInsertIndex } from "@/hooks/use-thread-chat-message-order";

type SubmitThreadMessage = StreamContextType["submit"];
type SubmitThreadOptions = NonNullable<Parameters<SubmitThreadMessage>[1]>;
type UseThreadChatOptions = {
  messages: LangGraphMessage[];
  isLoading: boolean;
  error: unknown;
  submit: SubmitThreadMessage;
  joinStream?: StreamContextType["joinStream"];
  onSubmitError?: (error: unknown) => void;
  threadId?: string;
  initialOptimisticUserText?: string;
  enableEnvironmentInitialization?: boolean;
  enableSyntheticPendingToolMessage?: boolean;
  enableBootstrapRunJoinStream?: boolean;
};

const DEFAULT_CONTEXT_WINDOW_TOKENS = 131072;

export function useThreadChat({
  messages,
  isLoading,
  error,
  submit,
  joinStream,
  onSubmitError,
  threadId,
  initialOptimisticUserText,
  enableEnvironmentInitialization = false,
  enableSyntheticPendingToolMessage = true,
  enableBootstrapRunJoinStream = true,
}: UseThreadChatOptions) {
  const [input, setInput] = useState("");
  const stabilizeStoreKey = useId();
  const normalizedThreadId = threadId?.trim() ?? "";
  const submitRef = useRef(submit);
  const onSubmitErrorRef = useRef(onSubmitError);
  const [lastValidTokenUsageSummary, setLastValidTokenUsageSummary] =
    useState<ThreadChatTokenUsageSummary | null>(null);
  const {
    environmentInitDisplay,
    initializeEnvironmentForPrompt,
    isEnvironmentBootstrapHydrated,
    isEnvironmentInitializing,
    isEnvironmentResetting,
    resetEnvironmentInitialization,
  } = useThreadEnvironmentBootstrap({
    threadId: normalizedThreadId,
    joinStream,
    messageCount: messages.length,
    enableEnvironmentInitialization,
    enableBootstrapRunJoinStream,
  });

  useEffect(() => {
    return () => {
      clearStabilizedThreadMessages(stabilizeStoreKey);
    };
  }, [stabilizeStoreKey]);

  useEffect(() => {
    submitRef.current = submit;
  }, [submit]);

  useEffect(() => {
    onSubmitErrorRef.current = onSubmitError;
  }, [onSubmitError]);

  useEffect(() => {
    setLastValidTokenUsageSummary(null);
  }, [normalizedThreadId]);

  const restoredInitialOptimisticUserText = useMemo(() => {
    return initialOptimisticUserText?.trim() ?? "";
  }, [initialOptimisticUserText]);

  const chatStatus = useMemo<ThreadChatStatus>(() => {
    if (error) return "error";
    if (isEnvironmentInitializing) return "submitted";
    return isLoading ? "streaming" : "ready";
  }, [error, isEnvironmentInitializing, isLoading]);

  const rawTokenUsageSummary = useMemo(
    () =>
      buildTokenUsageSummaryFromMessages(messages, DEFAULT_CONTEXT_WINDOW_TOKENS),
    [messages],
  );

  useEffect(() => {
    if (rawTokenUsageSummary.assistantMessagesWithUsageCount > 0) {
      setLastValidTokenUsageSummary(rawTokenUsageSummary);
    }
  }, [rawTokenUsageSummary]);

  const tokenUsageSummary = useMemo(() => {
    if (rawTokenUsageSummary.assistantMessagesWithUsageCount > 0) {
      return rawTokenUsageSummary;
    }

    if (
      !isLoading ||
      !lastValidTokenUsageSummary ||
      lastValidTokenUsageSummary.assistantMessagesWithUsageCount <= 0
    ) {
      return rawTokenUsageSummary;
    }

    return {
      ...rawTokenUsageSummary,
      assistantMessagesWithUsageCount:
        lastValidTokenUsageSummary.assistantMessagesWithUsageCount,
      latestInputTokens: lastValidTokenUsageSummary.latestInputTokens,
      latestOutputTokens: lastValidTokenUsageSummary.latestOutputTokens,
      latestTotalTokens: lastValidTokenUsageSummary.latestTotalTokens,
      latestContextUsageRatio:
        lastValidTokenUsageSummary.latestContextUsageRatio,
      latestModelName: lastValidTokenUsageSummary.latestModelName,
      latestMessageId: lastValidTokenUsageSummary.latestMessageId,
      cumulativeInputTokens: lastValidTokenUsageSummary.cumulativeInputTokens,
      cumulativeOutputTokens: lastValidTokenUsageSummary.cumulativeOutputTokens,
      cumulativeTotalTokens: lastValidTokenUsageSummary.cumulativeTotalTokens,
    };
  }, [isLoading, lastValidTokenUsageSummary, rawTokenUsageSummary]);

  const normalizedChatMessages = useMemo<ThreadChatDisplayMessage[]>(() => {
    return normalizeThreadChatMessages({
      messages,
      isLoading,
      enableSyntheticPendingToolMessage,
      stabilizeStoreKey,
    });
  }, [enableSyntheticPendingToolMessage, isLoading, messages, stabilizeStoreKey]);
  const {
    appendFailedTurnRecord,
    clearOptimisticDraft,
    createOptimisticDraft,
    failedTurnRecords,
    optimisticUserDraft,
  } = useThreadChatTurnState({
    error,
    environmentInitDisplay,
    initialOptimisticUserText: restoredInitialOptimisticUserText,
    isLoading,
    normalizedChatMessages,
    threadId: normalizedThreadId,
  });

  const environmentInitMessages = useMemo<ThreadChatDisplayMessage[]>(() => {
    if (!environmentInitDisplay) return [];
    const output = buildEnvironmentInitOutput(environmentInitDisplay);
    return [
      {
        id: `environment-init-${environmentInitDisplay.id}`,
        role: "assistant",
        parts: [
          {
            id: `environment-init-part-${environmentInitDisplay.id}`,
            type: "environment",
            title: buildEnvironmentInitTitle(environmentInitDisplay),
            status: environmentInitDisplay.status,
            output,
            steps: environmentInitDisplay.steps,
            logs: environmentInitDisplay.logs,
            error: environmentInitDisplay.error,
            runId: environmentInitDisplay.runId,
            runStatus: environmentInitDisplay.runStatus,
          },
        ],
      },
    ];
  }, [environmentInitDisplay]);

  const chatMessages = useMemo<ThreadChatDisplayMessage[]>(() => {
    const baseMessages =
      environmentInitMessages.length === 0
        ? normalizedChatMessages
        : [...environmentInitMessages, ...normalizedChatMessages];

    const getUserContent = (message: ThreadChatDisplayMessage) => {
      if (message.role !== "user") return "";
      const contentPart = message.parts.find((part) => part.type === "content");
      return contentPart?.content.trim() ?? "";
    };
    const baseUserMessages = baseMessages.filter(
      (message): message is ThreadChatDisplayMessage => message.role === "user",
    );
    const baseUserIdSet = new Set(baseUserMessages.map((message) => message.id));

    const failedByUserMessageId = new Map<string, FailedTurnRecord[]>();
    const orphanFailedTurns: FailedTurnRecord[] = [];
    failedTurnRecords.forEach((failedTurn) => {
      if (!baseUserIdSet.has(failedTurn.userMessageId)) {
        orphanFailedTurns.push(failedTurn);
        return;
      }
      const current = failedByUserMessageId.get(failedTurn.userMessageId) ?? [];
      failedByUserMessageId.set(failedTurn.userMessageId, [
        ...current,
        failedTurn,
      ]);
    });

    // 提交成功后后端 human 消息 id 会变化，这里按文本顺序把 orphan 失败回填到对应 user。
    const unmatchedUsers = baseUserMessages
      .filter((message) => !failedByUserMessageId.has(message.id))
      .map((message) => ({
        id: message.id,
        text: getUserContent(message),
      }));
    const trueOrphanFailedTurns: FailedTurnRecord[] = [];
    orphanFailedTurns.forEach((failedTurn) => {
      const failedUserText = failedTurn.userText.trim();
      const matchedUserIndex = unmatchedUsers.findIndex(
        (user) => user.text && user.text === failedUserText,
      );
      if (matchedUserIndex < 0) {
        trueOrphanFailedTurns.push(failedTurn);
        return;
      }

      const matchedUser = unmatchedUsers[matchedUserIndex];
      unmatchedUsers.splice(matchedUserIndex, 1);
      const current = failedByUserMessageId.get(matchedUser.id) ?? [];
      failedByUserMessageId.set(matchedUser.id, [...current, failedTurn]);
    });

    const mergedMessages = baseMessages.flatMap((message) => {
      if (message.role !== "user") return [message];
      const failedTurns = failedByUserMessageId.get(message.id) ?? [];
      if (failedTurns.length === 0) return [message];
      return [
        message,
        ...failedTurns.map(
          (failedTurn): ThreadChatDisplayMessage => ({
            id: `assistant-${failedTurn.id}`,
            role: "assistant",
            parts: [
              {
                id: `${failedTurn.id}-content`,
                type: "content",
                content: `本轮请求失败：${failedTurn.errorMessage}`,
              },
            ],
          }),
        ),
      ];
    });

    const mergedWithOrphans =
      trueOrphanFailedTurns.length === 0
        ? mergedMessages
        : [
          ...mergedMessages,
          ...trueOrphanFailedTurns.flatMap(
            (failedTurn): ThreadChatDisplayMessage[] => [
              {
                id: failedTurn.userMessageId,
                role: "user",
                parts: [
                  {
                    id: `${failedTurn.id}-user-content`,
                    type: "content",
                    content: failedTurn.userText,
                  },
                ],
              },
              {
                id: `assistant-${failedTurn.id}`,
                role: "assistant",
                parts: [
                  {
                    id: `${failedTurn.id}-content`,
                    type: "content",
                    content: `本轮请求失败：${failedTurn.errorMessage}`,
                  },
                ],
              },
            ],
          ),
        ];

    // 兜底：流式阶段若因消息快照切换导致失败记录未被挂载，
    // 强制补齐缺失的失败消息，确保历史失败不会“消失”。
    const renderedFailedRecordIds = new Set(
      mergedWithOrphans
        .map((message) => message.id)
        .filter((id) => id.startsWith("assistant-failed-turn-"))
        .map((id) => id.replace("assistant-", "")),
    );
    const missingFailedTurns = failedTurnRecords.filter(
      (failedTurn) => !renderedFailedRecordIds.has(failedTurn.id),
    );
    const mergedWithFailureFallback =
      missingFailedTurns.length === 0
        ? mergedWithOrphans
        : [
          ...mergedWithOrphans,
          ...missingFailedTurns.flatMap(
            (failedTurn): ThreadChatDisplayMessage[] => [
              {
                id: failedTurn.userMessageId,
                role: "user",
                parts: [
                  {
                    id: `${failedTurn.id}-user-content-fallback`,
                    type: "content",
                    content: failedTurn.userText,
                  },
                ],
              },
              {
                id: `assistant-${failedTurn.id}`,
                role: "assistant",
                parts: [
                  {
                    id: `${failedTurn.id}-content-fallback`,
                    type: "content",
                    content: `本轮请求失败：${failedTurn.errorMessage}`,
                  },
                ],
              },
            ],
          ),
        ];

    if (!optimisticUserDraft) return mergedWithFailureFallback;

    const hasMatchedUserMessage = mergedWithFailureFallback.some((message) => {
      if (message.role !== "user") return false;
      return message.parts.some(
        (part) =>
          part.type === "content" &&
          part.content.trim() === optimisticUserDraft.text,
      );
    });

    if (hasMatchedUserMessage) return mergedWithFailureFallback;

    const optimisticUserMessage: ThreadChatDisplayMessage = {
      id: optimisticUserDraft.id,
      role: "user",
      parts: [
        {
          id: `${optimisticUserDraft.id}-content`,
          type: "content",
          content: optimisticUserDraft.text,
        },
      ],
    };

    const optimisticInsertIndex =
      getOptimisticUserInsertIndex(mergedWithFailureFallback);

    return [
      ...mergedWithFailureFallback.slice(0, optimisticInsertIndex),
      optimisticUserMessage,
      ...mergedWithFailureFallback.slice(optimisticInsertIndex),
    ];
  }, [
    environmentInitMessages,
    failedTurnRecords,
    normalizedChatMessages,
    optimisticUserDraft,
  ]);

  const isThinking = (() => {
    if (!isLoading) return false;
    if (chatMessages.length === 0) return false;

    const lastUserIndex = [...chatMessages]
      .map((message) => message.role)
      .lastIndexOf("user");
    const currentTurn =
      lastUserIndex < 0 ? chatMessages : chatMessages.slice(lastUserIndex + 1);
    if (currentTurn.length === 0) return false;

    const lastTurnMessage = currentTurn[currentTurn.length - 1];
    if (!lastTurnMessage || lastTurnMessage.role !== "assistant") return false;

    const hasReasoningPart = lastTurnMessage.parts.some(
      (part) => part.type === "reasoning",
    );
    const hasContentPart = lastTurnMessage.parts.some(
      (part) => part.type === "content" && part.content.trim().length > 0,
    );

    return hasReasoningPart && !hasContentPart;
  })();

  const handleSubmit = useCallback(
    async ({ text, files }: PromptInputMessage) => {
      const trimmedText = text.trim();
      if (!trimmedText && (files?.length ?? 0) === 0) return;
      if (!trimmedText) return;

      const optimisticDraft = createOptimisticDraft(trimmedText);

      try {
        const handledByBootstrap =
          await initializeEnvironmentForPrompt(trimmedText);
        if (handledByBootstrap) {
          setInput("");
          return;
        }

        const submitOptions: SubmitThreadOptions = {
          streamMode: ["messages-tuple"],
          metadata: { name: trimmedText },
        };
        await submitRef.current(
          { messages: [{ type: "human", content: trimmedText }] },
          submitOptions,
        );
        setInput("");
      } catch (submitError) {
        clearOptimisticDraft();
        const submitErrorMessage =
          getErrorMessageText(submitError) || "请求失败，请稍后重试";
        appendFailedTurnRecord({
          userMessageId: optimisticDraft.id,
          userText: trimmedText,
          errorMessage: submitErrorMessage,
        });
        if (onSubmitErrorRef.current) {
          onSubmitErrorRef.current(submitError);
        } else {
          console.error("Failed to submit thread message", submitError);
        }
      }
    },
    [
      appendFailedTurnRecord,
      clearOptimisticDraft,
      createOptimisticDraft,
      initializeEnvironmentForPrompt,
    ],
  );

  return {
    input,
    setInput,
    chatStatus,
    chatMessages,
    immediateResponding: Boolean(optimisticUserDraft),
    hasTurnFailureMessages: failedTurnRecords.length > 0,
    isEnvironmentBootstrapHydrated,
    tokenUsageSummary,
    isThinking,
    handleSubmit,
    isEnvironmentResetting,
    resetEnvironmentInitialization,
  };
}
