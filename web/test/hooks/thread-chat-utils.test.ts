import test from 'node:test';
import assert from 'node:assert/strict';
import { type Message as LangGraphMessage } from '@langchain/langgraph-sdk';
import { normalizeThreadChatMessages } from '../../src/hooks/thread-chat-utils.ts';

test('normalizeThreadChatMessages keeps execute status but only shows shell output body', () => {
  const messages: LangGraphMessage[] = [
    {
      type: 'ai',
      id: 'ai-1',
      content: '',
      tool_calls: [
        {
          id: 'call-1',
          name: 'execute',
          args: {
            command: 'echo hello'
          }
        }
      ]
    },
    {
      type: 'tool',
      id: 'tool-1',
      name: 'execute',
      tool_call_id: 'call-1',
      content: 'Exit code: 0\nTruncated: False\nOutput: hello\nworld'
    }
  ];

  const normalized = normalizeThreadChatMessages({
    messages,
    isLoading: false,
    enableSyntheticPendingToolMessage: false,
    stabilizeStoreKey: 'thread-chat-utils-test-success'
  });

  assert.equal(normalized.length, 1);
  const toolPart = normalized[0]?.parts[0];
  assert.ok(toolPart && toolPart.type === 'tool');
  assert.equal(toolPart.status, 'success');
  assert.equal(toolPart.toolInvocation, 'echo hello');
  assert.equal(toolPart.content, 'hello\nworld');
});

test('normalizeThreadChatMessages preserves execute failure status while trimming shell wrapper fields', () => {
  const messages: LangGraphMessage[] = [
    {
      type: 'ai',
      id: 'ai-2',
      content: '',
      tool_calls: [
        {
          id: 'call-2',
          name: 'execute',
          args: {
            command: 'cat missing.txt'
          }
        }
      ]
    },
    {
      type: 'tool',
      id: 'tool-2',
      name: 'execute',
      tool_call_id: 'call-2',
      content:
        'Exit code: 1\nTruncated: False\nOutput: cat: missing.txt: No such file or directory'
    }
  ];

  const normalized = normalizeThreadChatMessages({
    messages,
    isLoading: false,
    enableSyntheticPendingToolMessage: false,
    stabilizeStoreKey: 'thread-chat-utils-test-error'
  });

  assert.equal(normalized.length, 1);
  const toolPart = normalized[0]?.parts[0];
  assert.ok(toolPart && toolPart.type === 'tool');
  assert.equal(toolPart.status, 'error');
  assert.equal(
    toolPart.content,
    'cat: missing.txt: No such file or directory'
  );
});

test('normalizeThreadChatMessages does not add a blank first line when Output header is standalone', () => {
  const messages: LangGraphMessage[] = [
    {
      type: 'ai',
      id: 'ai-3',
      content: '',
      tool_calls: [
        {
          id: 'call-3',
          name: 'execute',
          args: {
            command: 'pwd'
          }
        }
      ]
    },
    {
      type: 'tool',
      id: 'tool-3',
      name: 'execute',
      tool_call_id: 'call-3',
      content: 'Exit code: 0\nTruncated: False\nOutput:\n/Users/demo/project'
    }
  ];

  const normalized = normalizeThreadChatMessages({
    messages,
    isLoading: false,
    enableSyntheticPendingToolMessage: false,
    stabilizeStoreKey: 'thread-chat-utils-test-output-header'
  });

  const toolPart = normalized[0]?.parts[0];
  assert.ok(toolPart && toolPart.type === 'tool');
  assert.equal(toolPart.content, '/Users/demo/project');
});

test('normalizeThreadChatMessages falls back to raw shell content when structured wrapper is incomplete', () => {
  const rawContent = 'Exit code: 0\nOutput: hello';
  const messages: LangGraphMessage[] = [
    {
      type: 'ai',
      id: 'ai-4',
      content: '',
      tool_calls: [
        {
          id: 'call-4',
          name: 'execute',
          args: {
            command: 'echo hello'
          }
        }
      ]
    },
    {
      type: 'tool',
      id: 'tool-4',
      name: 'execute',
      tool_call_id: 'call-4',
      content: rawContent
    }
  ];

  const normalized = normalizeThreadChatMessages({
    messages,
    isLoading: false,
    enableSyntheticPendingToolMessage: false,
    stabilizeStoreKey: 'thread-chat-utils-test-fallback'
  });

  const toolPart = normalized[0]?.parts[0];
  assert.ok(toolPart && toolPart.type === 'tool');
  assert.equal(toolPart.content, rawContent);
});
