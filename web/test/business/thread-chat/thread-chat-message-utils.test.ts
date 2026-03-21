import test from 'node:test';
import assert from 'node:assert/strict';
import {
  getCopyMetaList,
  getConversationFileChanges,
  getTurnFileChangeSummaries,
  getToolChangeDisplayState,
  getToolTitle,
  getToolTitleTooltip,
  shouldRenderToolDiffContent,
  getUserTurns,
  hasCompletedAssistantReplyInTurn,
  shouldRenderMessagePartsInOriginalOrder
} from '../../../src/business/thread-chat/thread-chat-message-utils.ts';
import { mergeSequentialEditToolMessages } from '../../../src/business/thread-chat/thread-chat-tool-group.tsx';
import type { ThreadChatDisplayMessage } from '../../../src/business/thread-chat/types.ts';

test('assistant grouped reply with tool parts keeps original part order mode', () => {
  const message: ThreadChatDisplayMessage = {
    id: 'assistant-group-1',
    role: 'assistant',
    parts: [
      { id: 'p1', type: 'content', content: '先给出说明' },
      {
        id: 'p2',
        type: 'tool',
        toolName: 'read_file',
        toolCallId: 'call-1',
        status: 'success',
        content: '读取完成'
      },
      { id: 'p3', type: 'content', content: '再补充结论' }
    ]
  };

  assert.equal(shouldRenderMessagePartsInOriginalOrder(message), true);
});

test('assistant reply without tool part does not enter original-order mode', () => {
  const message: ThreadChatDisplayMessage = {
    id: 'assistant-plain-1',
    role: 'assistant',
    parts: [{ id: 'p1', type: 'content', content: '只有普通文本' }]
  };

  assert.equal(shouldRenderMessagePartsInOriginalOrder(message), false);
});

test('getToolTitle localizes common single-tool titles', () => {
  assert.equal(getToolTitle('apply_patch', 'src/a.ts'), '编辑文件 a.ts');
  assert.equal(
    getToolTitle('execute', 'cat /workspace/README.md'),
    '浏览 README.md'
  );
  assert.equal(
    getToolTitle('execute', 'ls -la /workspace'),
    '查看 workspace 目录'
  );
  assert.equal(
    getToolTitle('execute', 'find /workspace -name "pyproject.toml" | head -5'),
    '查找 pyproject.toml'
  );
  assert.equal(
    getToolTitle('execute', 'rg -n "auth" /workspace'),
    '搜索 auth'
  );
  assert.equal(
    getToolTitle('write_file', 'src/a.ts,src/b.ts'),
    '写入文件 2 个文件'
  );
  assert.equal(getToolTitle('execute', 'npm test'), '执行 npm test');
  assert.equal(getToolTitle('update_plan'), '更新计划');
});

test('getToolTitleTooltip exposes full targets when title is shortened', () => {
  assert.equal(
    getToolTitleTooltip('apply_patch', 'src/components/button.tsx'),
    'src/components/button.tsx'
  );
  assert.equal(
    getToolTitleTooltip('execute', 'cat /workspace/README.md'),
    '/workspace/README.md'
  );
  assert.equal(getToolTitleTooltip('execute', 'ls -la /workspace'), '/workspace');
  assert.equal(
    getToolTitleTooltip('execute', 'find /workspace -name "pyproject.toml" | head -5'),
    'pyproject.toml'
  );
  assert.equal(
    getToolTitleTooltip('execute', 'rg -n "auth middleware" /workspace'),
    'auth middleware'
  );
  assert.equal(getToolTitleTooltip('execute', 'npm test'), undefined);
  assert.equal(getToolTitleTooltip('update_plan'), undefined);
});

test('conversation file change summary deduplicates overlapping hunks for same file', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'tool-1',
      role: 'tool',
      parts: [
        {
          id: 'tool-1-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/search-form.vue',
          toolCallId: 'call-1',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 100,
          toolRemovedCount: 100,
          diffOldValue: 'old-1',
          diffNewValue: 'new-1',
          diffHunks: [{ oldStart: 100, oldCount: 100, newStart: 100, newCount: 100 }]
        }
      ]
    },
    {
      id: 'tool-2',
      role: 'tool',
      parts: [
        {
          id: 'tool-2-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/search-form.vue',
          toolCallId: 'call-2',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 100,
          toolRemovedCount: 100,
          diffOldValue: 'old-2',
          diffNewValue: 'new-2',
          diffHunks: [{ oldStart: 100, oldCount: 100, newStart: 100, newCount: 100 }]
        }
      ]
    }
  ];

  const [change] = getConversationFileChanges(messages);
  assert.ok(change);
  assert.equal(change.added, 200);
  assert.equal(change.removed, 200);
  assert.equal(change.editCount, 2);
});

test('conversation file change summary accumulates apply_patch stats while keeping latest visual diff', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'tool-latest-1',
      role: 'tool',
      parts: [
        {
          id: 'tool-latest-1-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.vue',
          toolCallId: 'latest-1',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 40,
          toolRemovedCount: 35,
          diffOldValue: 'old-1',
          diffNewValue: 'new-1'
        }
      ]
    },
    {
      id: 'tool-latest-2',
      role: 'tool',
      parts: [
        {
          id: 'tool-latest-2-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.vue',
          toolCallId: 'latest-2',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 8,
          toolRemovedCount: 11,
          diffOldValue: 'old-2',
          diffNewValue: 'new-2'
        }
      ]
    }
  ];

  const [change] = getConversationFileChanges(messages);
  assert.ok(change);
  assert.equal(change.added, 48);
  assert.equal(change.removed, 46);
  assert.equal(change.editCount, 2);
  assert.equal(change.diffOldValue, 'old-2');
  assert.equal(change.diffNewValue, 'new-2');
});

test('conversation file change summary resets prior edits after full file rewrite', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'tool-a',
      role: 'tool',
      parts: [
        {
          id: 'tool-a-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'call-a',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 20,
          toolRemovedCount: 20,
          diffOldValue: 'old-a',
          diffNewValue: 'new-a',
          diffHunks: [{ oldStart: 1, oldCount: 20, newStart: 1, newCount: 20 }]
        }
      ]
    },
    {
      id: 'tool-b',
      role: 'tool',
      parts: [
        {
          id: 'tool-b-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'call-b',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 30,
          toolRemovedCount: 30,
          diffOldValue: 'old-b',
          diffNewValue: 'new-b',
          diffHunks: [{ oldStart: 40, oldCount: 30, newStart: 40, newCount: 30 }]
        }
      ]
    },
    {
      id: 'tool-c',
      role: 'tool',
      parts: [
        {
          id: 'tool-c-part',
          type: 'tool',
          toolName: 'write_file',
          toolInvocation: 'a.vue',
          toolCallId: 'call-c',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 140,
          toolRemovedCount: 0,
          diffOldValue: '',
          diffNewValue: 'rewritten'
        }
      ]
    }
  ];

  const [change] = getConversationFileChanges(messages);
  assert.ok(change);
  assert.equal(change.added, 140);
  assert.equal(change.removed, 0);
  assert.equal(change.editCount, 1);
});

test('conversation file change summary resets prior edits for non-hunk rewrite snapshot', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'tool-d',
      role: 'tool',
      parts: [
        {
          id: 'tool-d-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'call-d',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 20,
          toolRemovedCount: 20,
          diffOldValue: 'old-d',
          diffNewValue: 'new-d',
          diffHunks: [{ oldStart: 1, oldCount: 20, newStart: 1, newCount: 20 }]
        }
      ]
    },
    {
      id: 'tool-e',
      role: 'tool',
      parts: [
        {
          id: 'tool-e-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'call-e',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 30,
          toolRemovedCount: 30,
          diffOldValue: 'old-e',
          diffNewValue: 'new-e',
          diffHunks: [{ oldStart: 40, oldCount: 30, newStart: 40, newCount: 30 }]
        }
      ]
    },
    {
      id: 'tool-f',
      role: 'tool',
      parts: [
        {
          id: 'tool-f-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'call-f',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 140,
          toolRemovedCount: 80,
          diffOldValue: 'deleted-old-content',
          diffNewValue: 'rewritten-new-content'
        }
      ]
    }
  ];

  const [change] = getConversationFileChanges(messages);
  assert.ok(change);
  assert.equal(change.added, 190);
  assert.equal(change.removed, 130);
  assert.equal(change.editCount, 3);
});

test('conversation file change summary ignores failed tool diffs', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'tool-failed',
      role: 'tool',
      parts: [
        {
          id: 'tool-failed-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'packages/components/src/search-form/src/search-form.vue',
          toolCallId: 'call-failed',
          status: 'error',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 120,
          toolRemovedCount: 110,
          diffOldValue: 'broken-old',
          diffNewValue: 'broken-new'
        }
      ]
    },
    {
      id: 'tool-rm',
      role: 'tool',
      parts: [
        {
          id: 'tool-rm-part',
          type: 'tool',
          toolName: 'execute',
          toolInvocation: 'rm packages/components/src/search-form/src/search-form.vue',
          toolCallId: 'call-rm',
          status: 'success',
          content: '',
          contentFormat: 'shell'
        }
      ]
    },
    {
      id: 'tool-add',
      role: 'tool',
      parts: [
        {
          id: 'tool-add-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'packages/components/src/search-form/src/search-form.vue',
          toolCallId: 'call-add',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 140,
          toolRemovedCount: 0,
          diffOldValue: '',
          diffNewValue: 'rewritten-file'
        }
      ]
    }
  ];

  const [change] = getConversationFileChanges(messages);
  assert.ok(change);
  assert.equal(change.added, 140);
  assert.equal(change.removed, 0);
  assert.equal(change.editCount, 1);
});

test('failed apply_patch does not expose diff stats or merged diff content', () => {
  const failedPart: ThreadChatDisplayMessage['parts'][number] = {
    id: 'tool-failed-part',
    type: 'tool',
    toolName: 'apply_patch',
    toolInvocation: 'src/a.vue',
    toolCallId: 'call-failed',
    status: 'error',
    content: '',
    contentFormat: 'diff',
    toolAddedCount: 12,
    toolRemovedCount: 8,
    diffOldValue: 'broken-old',
    diffNewValue: 'broken-new'
  };

  const displayState = getToolChangeDisplayState(failedPart);
  assert.deepEqual(displayState, {
    added: 0,
    removed: 0,
    showAdded: false,
    showRemoved: false
  });

  const [mergedMessage] = mergeSequentialEditToolMessages([
    {
      id: 'tool-failed',
      role: 'tool',
      parts: [failedPart]
    },
    {
      id: 'tool-success',
      role: 'tool',
      parts: [
        {
          id: 'tool-success-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.vue',
          toolCallId: 'call-success',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 3,
          toolRemovedCount: 1,
          diffOldValue: 'stable-old',
          diffNewValue: 'stable-new'
        }
      ]
    }
  ]);

  assert.ok(mergedMessage);
  const mergedPart = mergedMessage.parts[0];
  assert.equal(mergedPart?.type, 'tool');
  if (mergedPart?.type !== 'tool') {
    assert.fail('expected merged tool part');
  }
  assert.equal(mergedPart.toolAddedCount, 3);
  assert.equal(mergedPart.toolRemovedCount, 1);
  assert.equal(mergedPart.diffOldValue, 'stable-old');
  assert.equal(mergedPart.diffNewValue, 'stable-new');
});

test('failed diff tool falls back to error content instead of diff viewer', () => {
  assert.equal(
    shouldRenderToolDiffContent({
      id: 'tool-error-part',
      type: 'tool',
      toolName: 'apply_patch',
      toolInvocation: 'src/a.vue',
      toolCallId: 'call-error',
      status: 'error',
      content: 'Failed to apply patch',
      contentFormat: 'diff',
      diffOldValue: 'old',
      diffNewValue: 'new'
    }),
    false
  );

  assert.equal(
    shouldRenderToolDiffContent({
      id: 'tool-success-part',
      type: 'tool',
      toolName: 'apply_patch',
      toolInvocation: 'src/a.vue',
      toolCallId: 'call-success',
      status: 'success',
      content: '',
      contentFormat: 'diff',
      diffOldValue: 'old',
      diffNewValue: 'new'
    }),
    true
  );
});

test('latest turn without final assistant reply is still considered unfinished', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'user-1',
      role: 'user',
      parts: [{ id: 'user-1-content', type: 'content', content: '改一下文件' }]
    },
    {
      id: 'assistant-1',
      role: 'assistant',
      finishReason: 'tool_calls',
      parts: [
        {
          id: 'assistant-1-tool',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.ts',
          toolCallId: 'call-1',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 3,
          toolRemovedCount: 1,
          diffOldValue: 'old',
          diffNewValue: 'new'
        }
      ]
    },
    {
      id: 'tool-1',
      role: 'tool',
      parts: [
        {
          id: 'tool-1-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.ts',
          toolCallId: 'call-1',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 3,
          toolRemovedCount: 1,
          diffOldValue: 'old',
          diffNewValue: 'new'
        }
      ]
    }
  ];

  const [turn] = getUserTurns(messages);
  assert.ok(turn);
  assert.equal(hasCompletedAssistantReplyInTurn(messages, turn), false);
});

test('latest turn with final assistant reply is considered finished', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'user-2',
      role: 'user',
      parts: [{ id: 'user-2-content', type: 'content', content: '改好了没' }]
    },
    {
      id: 'assistant-2-tool',
      role: 'assistant',
      finishReason: 'tool_calls',
      parts: [
        {
          id: 'assistant-2-tool-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.ts',
          toolCallId: 'call-2',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 1,
          toolRemovedCount: 1,
          diffOldValue: 'old',
          diffNewValue: 'new'
        }
      ]
    },
    {
      id: 'assistant-2-final',
      role: 'assistant',
      finishReason: 'stop',
      parts: [{ id: 'assistant-2-content', type: 'content', content: '已经改好。' }]
    }
  ];

  const [turn] = getUserTurns(messages);
  assert.ok(turn);
  assert.equal(hasCompletedAssistantReplyInTurn(messages, turn), true);
});

test('turn file change summaries avoid duplicate cards when later turns stream', () => {
  const baseMessages: ThreadChatDisplayMessage[] = [
    {
      id: 'user-1',
      role: 'user',
      parts: [{ id: 'user-1-part', type: 'content', content: '第一轮' }]
    },
    {
      id: 'assistant-1',
      role: 'assistant',
      finishReason: 'stop',
      parts: [
        { id: 'assistant-1-part', type: 'content', content: '无需改动。' }
      ]
    },
    {
      id: 'user-2',
      role: 'user',
      parts: [{ id: 'user-2-part', type: 'content', content: '第二轮改一下' }]
    },
    {
      id: 'tool-2',
      role: 'tool',
      parts: [
        {
          id: 'tool-2-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/a.ts',
          toolCallId: 'call-2',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 2,
          toolRemovedCount: 1,
          diffOldValue: 'old',
          diffNewValue: 'new'
        }
      ]
    },
    {
      id: 'assistant-2',
      role: 'assistant',
      finishReason: 'stop',
      parts: [{ id: 'assistant-2-part', type: 'content', content: '已修改。' }]
    }
  ];

  const firstSummaries = getTurnFileChangeSummaries(baseMessages);
  assert.equal(firstSummaries.length, 1);
  assert.equal(firstSummaries[0]?.userIndex, 2);

  const nextMessages: ThreadChatDisplayMessage[] = [
    ...baseMessages,
    {
      id: 'user-3',
      role: 'user',
      parts: [{ id: 'user-3-part', type: 'content', content: '第三轮' }]
    },
    {
      id: 'assistant-3',
      role: 'assistant',
      finishReason: 'tool_calls',
      parts: [
        {
          id: 'assistant-3-tool',
          type: 'tool',
          toolName: 'read_file',
          toolInvocation: 'src/a.ts',
          toolCallId: 'call-3',
          status: 'success',
          content: '',
          contentFormat: 'shell'
        }
      ]
    }
  ];

  const secondSummaries = getTurnFileChangeSummaries(nextMessages);
  const summaryIds = secondSummaries.map((summary) => summary.id);
  assert.equal(
    summaryIds.filter((id) => id === 'turn-file-change-2-4').length,
    1
  );
});

test('copy action anchors to the last visible ai-side message in the turn', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'user-copy-anchor',
      role: 'user',
      parts: [{ id: 'user-copy-anchor-content', type: 'content', content: '继续改' }]
    },
    {
      id: 'assistant-copy-anchor',
      role: 'assistant',
      finishReason: 'stop',
      parts: [
        {
          id: 'assistant-copy-anchor-content',
          type: 'content',
          content: '现在继续优化下拉菜单和其他元素的扁平风格。'
        }
      ]
    },
    {
      id: 'tool-copy-anchor',
      role: 'tool',
      parts: [
        {
          id: 'tool-copy-anchor-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'src/theme.scss',
          toolCallId: 'copy-anchor-call',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 12,
          toolRemovedCount: 5,
          diffOldValue: 'old',
          diffNewValue: 'new'
        }
      ]
    }
  ];

  const copyMeta = getCopyMetaList(messages);

  assert.deepEqual(copyMeta[1], {
    canCopy: false,
    copyText: ''
  });
  assert.equal(copyMeta[2]?.canCopy, true);
  assert.match(
    copyMeta[2]?.copyText ?? '',
    /现在继续优化下拉菜单和其他元素的扁平风格。/
  );
});

test('merged sequential edit tool message reuses deduplicated file stats', () => {
  const messages: ThreadChatDisplayMessage[] = [
    {
      id: 'merge-tool-1',
      role: 'tool',
      parts: [
        {
          id: 'merge-tool-1-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'merge-call-1',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 100,
          toolRemovedCount: 100,
          diffOldValue: 'old-1',
          diffNewValue: 'new-1',
          diffHunks: [{ oldStart: 100, oldCount: 100, newStart: 100, newCount: 100 }]
        }
      ]
    },
    {
      id: 'merge-tool-2',
      role: 'tool',
      parts: [
        {
          id: 'merge-tool-2-part',
          type: 'tool',
          toolName: 'apply_patch',
          toolInvocation: 'a.vue',
          toolCallId: 'merge-call-2',
          status: 'success',
          content: '',
          contentFormat: 'diff',
          toolAddedCount: 100,
          toolRemovedCount: 100,
          diffOldValue: 'old-2',
          diffNewValue: 'new-2',
          diffHunks: [{ oldStart: 100, oldCount: 100, newStart: 100, newCount: 100 }]
        }
      ]
    }
  ];

  const [merged] = mergeSequentialEditToolMessages(messages);
  assert.ok(merged);
  const mergedPart = merged.parts[0];
  assert.equal(mergedPart?.type, 'tool');
  if (mergedPart?.type !== 'tool') {
    assert.fail('expected merged tool part');
  }
  assert.equal(mergedPart.toolAddedCount, 200);
  assert.equal(mergedPart.toolRemovedCount, 200);
});
