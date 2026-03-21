import { useCallback, useEffect, useRef, useState } from "react";
import { type ThreadChatDisplayMessage } from "@/business/thread-chat/types";
import {
  type EnvironmentInitDisplay,
  getErrorMessageText,
  readBootstrapOptimisticUserText,
  writeBootstrapOptimisticUserText,
} from "@/hooks/thread-chat-utils";

export type FailedTurnRecord = {
  id: string;
  userMessageId: string;
  userText: string;
  errorMessage: string;
  errorKey: string;
};

export type OptimisticUserDraft = {
  id: string;
  text: string;
  createdMessageCount: number;
};

type UseThreadChatTurnStateOptions = {
  error: unknown;
  environmentInitDisplay: EnvironmentInitDisplay | null;
  initialOptimisticUserText?: string;
  isLoading: boolean;
  normalizedChatMessages: ThreadChatDisplayMessage[];
  threadId: string;
};

export const shouldClearOptimisticDraftAfterAssistantReply = ({
  normalizedChatMessages,
  optimisticUserDraft,
}: {
  isLoading: boolean;
  normalizedChatMessages: ThreadChatDisplayMessage[];
  optimisticUserDraft: OptimisticUserDraft | null;
}) => {
  if (!optimisticUserDraft) return false;

  const startIndex = Math.max(0, optimisticUserDraft.createdMessageCount);
  const newMessages = normalizedChatMessages.slice(startIndex);

  if (newMessages.length === 0) return false;

  // 检查是否有任何 assistant 或 tool 消息（tool 消息也属于 AI 回复的一部分）
  return newMessages.some((message) =>
    message.role === "assistant" || message.role === "tool"
  );
};

export const shouldClearOptimisticDraftAfterEnvironmentSettles = ({
  environmentInitDisplay,
  optimisticUserDraft,
}: {
  environmentInitDisplay: EnvironmentInitDisplay | null;
  optimisticUserDraft: OptimisticUserDraft | null;
}) => {
  if (!optimisticUserDraft) return false;
  if (!environmentInitDisplay) return false;
  return environmentInitDisplay.status !== "running";
};

export function useThreadChatTurnState({
  error,
  environmentInitDisplay,
  initialOptimisticUserText,
  isLoading,
  normalizedChatMessages,
  threadId,
}: UseThreadChatTurnStateOptions) {
  const [optimisticUserDraft, setOptimisticUserDraft] =
    useState<OptimisticUserDraft | null>(null);
  const [failedTurnRecords, setFailedTurnRecords] = useState<FailedTurnRecord[]>(
    [],
  );
  const optimisticUserDraftSeqRef = useRef(0);
  const failedTurnSeqRef = useRef(0);

  useEffect(() => {
    setOptimisticUserDraft(null);
    setFailedTurnRecords([]);
  }, [threadId]);

  useEffect(() => {
    if (!optimisticUserDraft) return;

    const startIndex = Math.max(0, optimisticUserDraft.createdMessageCount);
    const newMessages = normalizedChatMessages.slice(startIndex);

    const hasNewUserMessage = newMessages.some((message) => {
      if (message.role !== "user") return false;
      return message.parts.some(
        (part) =>
          part.type === "content" &&
          part.content.trim().length > 0,
      );
    });

    if (hasNewUserMessage) {
      writeBootstrapOptimisticUserText(threadId, "");
      setOptimisticUserDraft(null);
    }
  }, [normalizedChatMessages, optimisticUserDraft, threadId]);

  useEffect(() => {
    if (!optimisticUserDraft) return;
    if (
      !shouldClearOptimisticDraftAfterAssistantReply({
        isLoading,
        normalizedChatMessages,
        optimisticUserDraft,
      })
    ) {
      return;
    }

    writeBootstrapOptimisticUserText(threadId, "");
    setOptimisticUserDraft(null);
  }, [isLoading, normalizedChatMessages, optimisticUserDraft, threadId]);

  useEffect(() => {
    if (
      !shouldClearOptimisticDraftAfterEnvironmentSettles({
        environmentInitDisplay,
        optimisticUserDraft,
      })
    ) {
      return;
    }

    // 环境初始化消息是首轮链路的一部分；当它已经结束时，即便真实会话消息稍后才同步，
    // 也要及时清掉乐观草稿，避免“正在回复...”被 immediateResponding 长时间挂住。
    writeBootstrapOptimisticUserText(threadId, "");
    setOptimisticUserDraft(null);
  }, [environmentInitDisplay, optimisticUserDraft, threadId]);

  useEffect(() => {
    const restoredOptimisticUserText =
      initialOptimisticUserText?.trim() ?? readBootstrapOptimisticUserText(threadId);
    if (!restoredOptimisticUserText) return;

    const hasMatchedUserMessage = normalizedChatMessages.some((message) => {
      if (message.role !== "user") return false;
      return message.parts.some(
        (part) =>
          part.type === "content" &&
          part.content.trim() === restoredOptimisticUserText,
      );
    });
    if (hasMatchedUserMessage) {
      writeBootstrapOptimisticUserText(threadId, "");
      return;
    }

    writeBootstrapOptimisticUserText(threadId, restoredOptimisticUserText);

    setOptimisticUserDraft((currentDraft) => {
      if (currentDraft) return currentDraft;
      optimisticUserDraftSeqRef.current += 1;
      return {
        id: `optimistic-user-${optimisticUserDraftSeqRef.current}`,
        text: restoredOptimisticUserText,
        createdMessageCount: normalizedChatMessages.length,
      };
    });
  }, [initialOptimisticUserText, normalizedChatMessages, threadId]);

  useEffect(() => {
    const normalizedErrorMessage = getErrorMessageText(error);
    if (!normalizedErrorMessage) return;
    if (!threadId) return;

    const userMessageEntries = normalizedChatMessages
      .map((message, index) => ({ message, index }))
      .filter((entry) => entry.message.role === "user");
    if (userMessageEntries.length === 0) return;

    const unresolvedUserMessage = userMessageEntries.find((entry, entryIndex) => {
      const currentUserMessage = entry.message;
      if (
        failedTurnRecords.some(
          (record) => record.userMessageId === currentUserMessage.id,
        )
      ) {
        return false;
      }

      const nextUserIndex =
        userMessageEntries[entryIndex + 1]?.index ?? normalizedChatMessages.length;
      const hasAssistantConclusion = normalizedChatMessages
        .slice(entry.index + 1, nextUserIndex)
        .some(
          (message) =>
            message.role === "assistant" &&
            message.parts.some(
              (part) =>
                part.type === "content" && part.content.trim().length > 0,
            ),
        );
      return !hasAssistantConclusion;
    });
    if (!unresolvedUserMessage) return;

    const errorKey = `${unresolvedUserMessage.message.id}::${normalizedErrorMessage}`;
    setFailedTurnRecords((prev) => {
      if (prev.some((item) => item.errorKey === errorKey)) return prev;
      failedTurnSeqRef.current += 1;
      const lastUserText =
        unresolvedUserMessage.message.parts.find(
          (part) => part.type === "content",
        )?.content ?? "";
      return [
        ...prev,
        {
          id: `failed-turn-${failedTurnSeqRef.current}`,
          userMessageId: unresolvedUserMessage.message.id,
          userText: lastUserText,
          errorMessage: normalizedErrorMessage,
          errorKey,
        },
      ];
    });
  }, [error, failedTurnRecords, normalizedChatMessages, threadId]);

  const createOptimisticDraft = useCallback(
    (text: string) => {
      optimisticUserDraftSeqRef.current += 1;
      const optimisticDraftId = `optimistic-user-${optimisticUserDraftSeqRef.current}`;
      writeBootstrapOptimisticUserText(threadId, text);
      const nextDraft = {
        id: optimisticDraftId,
        text,
        createdMessageCount: normalizedChatMessages.length,
      };
      setOptimisticUserDraft(nextDraft);
      return nextDraft;
    },
    [normalizedChatMessages.length, threadId],
  );

  const clearOptimisticDraft = useCallback(() => {
    writeBootstrapOptimisticUserText(threadId, "");
    setOptimisticUserDraft(null);
  }, [threadId]);

  const appendFailedTurnRecord = useCallback(
    ({
      errorMessage,
      userMessageId,
      userText,
    }: {
      errorMessage: string;
      userMessageId: string;
      userText: string;
    }) => {
      failedTurnSeqRef.current += 1;
      setFailedTurnRecords((prev) => [
        ...prev,
        {
          id: `failed-turn-${failedTurnSeqRef.current}`,
          userMessageId,
          userText,
          errorMessage,
          errorKey: `${userMessageId}::${errorMessage}`,
        },
      ]);
    },
    [],
  );

  return {
    appendFailedTurnRecord,
    clearOptimisticDraft,
    createOptimisticDraft,
    failedTurnRecords,
    optimisticUserDraft,
  };
}
