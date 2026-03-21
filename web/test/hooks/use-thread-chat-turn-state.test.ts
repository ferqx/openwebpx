import test from "node:test";
import assert from "node:assert/strict";
import {
  shouldClearOptimisticDraftAfterAssistantReply,
  shouldClearOptimisticDraftAfterEnvironmentSettles,
  type OptimisticUserDraft,
} from "../../src/hooks/use-thread-chat-turn-state.ts";
import { type ThreadChatDisplayMessage } from "@/business/thread-chat/types";
import { type EnvironmentInitDisplay } from "@/hooks/thread-chat-utils";

test("clears optimistic draft once assistant reply lands after draft while idle", () => {
  const optimisticDraft: OptimisticUserDraft = {
    id: "optimistic-user-1",
    text: "请帮我改下",
    createdMessageCount: 0,
  };
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: "assistant-1",
      role: "assistant",
      parts: [
        { id: "assistant-1-part", type: "content", content: "已处理。" },
      ],
    },
  ];

  assert.equal(
    shouldClearOptimisticDraftAfterAssistantReply({
      isLoading: false,
      normalizedChatMessages: messages,
      optimisticUserDraft: optimisticDraft,
    }),
    true,
  );
});

test("does not clear optimistic draft when assistant reply is before draft index", () => {
  const optimisticDraft: OptimisticUserDraft = {
    id: "optimistic-user-1",
    text: "继续",
    createdMessageCount: 2,
  };
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: "assistant-1",
      role: "assistant",
      parts: [
        { id: "assistant-1-part", type: "content", content: "旧回复" },
      ],
    },
    {
      id: "user-1",
      role: "user",
      parts: [{ id: "user-1-part", type: "content", content: "上一轮" }],
    },
  ];

  assert.equal(
    shouldClearOptimisticDraftAfterAssistantReply({
      isLoading: false,
      normalizedChatMessages: messages,
      optimisticUserDraft: optimisticDraft,
    }),
    false,
  );
});

test("clears optimistic draft once assistant reply lands even while loading", () => {
  const optimisticDraft: OptimisticUserDraft = {
    id: "optimistic-user-1",
    text: "继续",
    createdMessageCount: 0,
  };
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: "assistant-1",
      role: "assistant",
      parts: [
        { id: "assistant-1-part", type: "content", content: "处理中" },
      ],
    },
  ];

  assert.equal(
    shouldClearOptimisticDraftAfterAssistantReply({
      isLoading: true,
      normalizedChatMessages: messages,
      optimisticUserDraft: optimisticDraft,
    }),
    true,
  );
});

test("environment init settled display should be able to end optimistic responding state", () => {
  const optimisticDraft: OptimisticUserDraft = {
    id: "optimistic-user-1",
    text: "启动环境并继续",
    createdMessageCount: 0,
  };
  const settledEnvironmentDisplay: EnvironmentInitDisplay = {
    id: "environment-init-1",
    status: "success",
    steps: [],
    logs: [],
  };

  assert.equal(
    shouldClearOptimisticDraftAfterEnvironmentSettles({
      environmentInitDisplay: settledEnvironmentDisplay,
      optimisticUserDraft: optimisticDraft,
    }),
    true,
  );
});
