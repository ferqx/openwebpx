import { type ReactNode } from 'react';
import { type PromptInputMessage } from '@/components/ai-elements/prompt-input';
import {
  type ThreadChatDisplayMessage,
  type ThreadChatStatus,
  type ThreadChatTokenUsageSummary
} from '@/business/thread-chat/types';
import { ThreadChatInputPanel } from '@/business/thread-chat/thread-chat-input-panel';
import { ThreadChatMessageList } from '@/business/thread-chat/thread-chat-message-list';

const toStreamErrorMessage = (error: unknown): string | undefined => {
  if (!error) return undefined;
  if (typeof error === 'string' && error.trim()) return error.trim();
  if (error instanceof Error && error.message.trim()) return error.message.trim();
  if (typeof error !== 'object') return undefined;

  const record = error as Record<string, unknown>;
  const directCandidates = [record.message, record.detail, record.error];
  for (const candidate of directCandidates) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }

  const nestedError = record.error;
  if (nestedError && typeof nestedError === 'object') {
    const nestedMessage = (nestedError as Record<string, unknown>).message;
    if (typeof nestedMessage === 'string' && nestedMessage.trim()) {
      return nestedMessage.trim();
    }
  }

  return undefined;
};

type ThreadChatPanelProps = {
  threadId?: string;
  chatMessages: ThreadChatDisplayMessage[];
  isLoading: boolean;
  isInitializing?: boolean;
  isThinking: boolean;
  chatStatus: ThreadChatStatus;
  immediateResponding?: boolean;
  hasTurnFailureMessages?: boolean;
  tokenUsageSummary?: ThreadChatTokenUsageSummary;
  error?: unknown;
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: (message: PromptInputMessage) => void | Promise<void>;
  onResetEnvironmentInitialization?: () => void | Promise<void>;
  isEnvironmentResetting?: boolean;
  onStopGenerating?: () => void;
  emptyTitle: string;
  emptyDescription?: string;
  emptyMedia?: ReactNode;
  placeholder: string;
  attachmentsLabel?: string;
  conversationContentClassName?: string;
  inputOuterClassName?: string;
  inputInnerClassName?: string;
};

export function ThreadChatPanel({
  threadId,
  chatMessages,
  isLoading,
  isInitializing = false,
  isThinking,
  chatStatus,
  immediateResponding = false,
  hasTurnFailureMessages = false,
  tokenUsageSummary,
  error: _error,
  input,
  onInputChange,
  onSubmit,
  onResetEnvironmentInitialization,
  isEnvironmentResetting = false,
  onStopGenerating,
  emptyTitle,
  emptyDescription,
  emptyMedia,
  placeholder,
  attachmentsLabel = '添加文件',
  conversationContentClassName,
  inputOuterClassName,
  inputInnerClassName
}: ThreadChatPanelProps) {
  const streamErrorMessage = toStreamErrorMessage(_error);
  return (
    <>
      <div className="min-h-0 flex-1">
        <ThreadChatMessageList
          threadId={threadId}
          chatMessages={chatMessages}
          streamErrorMessage={streamErrorMessage}
          hasTurnFailureMessages={hasTurnFailureMessages}
          isLoading={isLoading}
          isInitializing={isInitializing}
          isThinking={isThinking}
          chatStatus={chatStatus}
          immediateResponding={immediateResponding}
          onResetEnvironmentInitialization={onResetEnvironmentInitialization}
          isEnvironmentResetting={isEnvironmentResetting}
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
          emptyMedia={emptyMedia}
          conversationContentClassName={conversationContentClassName}
        />
      </div>
      <ThreadChatInputPanel
        chatStatus={chatStatus}
        tokenUsageSummary={tokenUsageSummary}
        input={input}
        onInputChange={onInputChange}
        onSubmit={onSubmit}
        onStopGenerating={onStopGenerating}
        placeholder={placeholder}
        attachmentsLabel={attachmentsLabel}
        inputOuterClassName={inputOuterClassName}
        inputInnerClassName={inputInnerClassName}
      />
    </>
  );
}
