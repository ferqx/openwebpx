import test from "node:test";
import assert from "node:assert/strict";
import { getOptimisticUserInsertIndex } from "../../src/hooks/use-thread-chat-message-order.ts";
import { type ThreadChatDisplayMessage } from "@/business/thread-chat/types";

test("optimistic user draft stays before first reply in initial auto-run turn", () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: "environment-init-1",
      role: "assistant",
      parts: [
        {
          id: "environment-part-1",
          type: "environment",
          title: "环境初始化中",
          status: "success",
          output: "",
          steps: [],
          logs: [],
        },
      ],
    },
    {
      id: "assistant-1",
      role: "assistant",
      parts: [
        {
          id: "assistant-content-1",
          type: "content",
          content: "我来探索当前的搜索组件样式。",
        },
      ],
    },
  ];

  assert.equal(getOptimisticUserInsertIndex(messages), 1);
});

test("optimistic user draft appends after a completed previous turn", () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: "user-1",
      role: "user",
      parts: [
        {
          id: "user-1-content",
          type: "content",
          content: "修改搜索组件样式扁平风格",
        },
      ],
    },
    {
      id: "assistant-1",
      role: "assistant",
      parts: [
        {
          id: "assistant-1-content",
          type: "content",
          content: "我先看一下当前实现。",
        },
      ],
    },
  ];

  assert.equal(getOptimisticUserInsertIndex(messages), 2);
});

test("optimistic user draft still follows the latest real user when reply has not arrived", () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: "user-1",
      role: "user",
      parts: [
        {
          id: "user-1-content",
          type: "content",
          content: "修改搜索组件样式扁平风格",
        },
      ],
    },
  ];

  assert.equal(getOptimisticUserInsertIndex(messages), 1);
});
