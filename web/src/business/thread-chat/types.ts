export type ThreadChatPart =
  | {
      type: 'reasoning';
      content: string;
      id: string;
    }
  | {
      type: 'content';
      content: string;
      id: string;
    }
  | {
      type: 'tool';
      id: string;
      toolName: string;
      toolInvocation?: string;
      toolAddedCount?: number;
      toolRemovedCount?: number;
      toolNetAddedCount?: number;
      toolNetRemovedCount?: number;
      toolCallId: string;
      status: 'running' | 'error' | 'success';
      content: string;
      contentFormat?: 'shell' | 'diff';
      diffOldValue?: string;
      diffNewValue?: string;
      diffLineOffset?: number;
      diffLineMode?: 'absolute' | 'relative';
      diffHunks?: Array<{
        oldStart: number;
        oldCount: number;
        newStart: number;
        newCount: number;
      }>;
      diffSections?: Array<{
        id: string;
        filePath?: string;
        oldValue?: string;
        newValue?: string;
        diffLineOffset?: number;
        diffLineMode?: 'absolute' | 'relative';
        diffHunks?: Array<{
          oldStart: number;
          oldCount: number;
          newStart: number;
          newCount: number;
        }>;
      }>;
    }
  | {
      type: 'environment';
      id: string;
      title: string;
      status: 'running' | 'error' | 'success';
      output: string;
      steps: Array<{
        key: string;
        title: string;
        status: 'pending' | 'running' | 'success' | 'error' | 'skipped';
        detail?: string;
      }>;
      logs: Array<{
        timestamp?: string | null;
        level?: string;
        message: string;
      }>;
      error?: string;
      runId?: string;
      runStatus?: string;
    };

export type ThreadChatDisplayMessage = {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  parts: ThreadChatPart[];
  finishReason?: string;
};

export type ThreadChatStatus = 'submitted' | 'streaming' | 'ready' | 'error';

export type ThreadChatTokenUsageSummary = {
  messageCount: number;
  userMessageCount: number;
  assistantMessageCount: number;
  toolMessageCount: number;
  otherMessageCount: number;
  assistantMessagesWithUsageCount: number;
  latestInputTokens: number;
  latestOutputTokens: number;
  latestTotalTokens: number;
  latestContextUsageRatio?: number;
  latestModelName?: string;
  latestMessageId?: string;
  cumulativeInputTokens: number;
  cumulativeOutputTokens: number;
  cumulativeTotalTokens: number;
  contextWindowTokens?: number;
};
