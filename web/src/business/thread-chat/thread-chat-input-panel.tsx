import { memo } from 'react';
import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  PromptInputFooter,
  type PromptInputMessage,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools
} from '@/components/ai-elements/prompt-input';
import { cn } from '@/lib/utils';
import {
  SUPPORTED_PROMPT_ATTACHMENT_ACCEPT,
  getPromptAttachmentErrorMessage
} from '@/lib/prompt-input-attachments';
import {
  type ThreadChatStatus,
  type ThreadChatTokenUsageSummary
} from '@/business/thread-chat/types';
import { toast } from 'sonner';

type ThreadChatInputPanelProps = {
  chatStatus: ThreadChatStatus;
  tokenUsageSummary?: ThreadChatTokenUsageSummary;
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: (message: PromptInputMessage) => void | Promise<void>;
  onStopGenerating?: () => void;
  placeholder: string;
  attachmentsLabel: string;
  inputOuterClassName?: string;
  inputInnerClassName?: string;
};

export const ThreadChatInputPanel = memo(
  ({
    chatStatus,
    tokenUsageSummary,
    input,
    onInputChange,
    onSubmit,
    onStopGenerating,
    placeholder,
    attachmentsLabel,
    inputOuterClassName,
    inputInnerClassName
  }: ThreadChatInputPanelProps) => {
    const hasTokenUsage =
      (tokenUsageSummary?.assistantMessagesWithUsageCount ?? 0) > 0;
    const contextWindowTokens = tokenUsageSummary?.contextWindowTokens ?? 131072;
    const latestInputTokens = tokenUsageSummary?.latestInputTokens ?? 0;
    const ratio =
      tokenUsageSummary?.latestContextUsageRatio ??
      (contextWindowTokens > 0 ? latestInputTokens / contextWindowTokens : 0);
    const ratioPercentText = `${Math.min(999.9, ratio * 100).toFixed(1)}%`;
    const warningToneClass =
      ratio >= 0.9
        ? 'text-red-600'
        : ratio >= 0.8
          ? 'text-amber-600'
          : 'text-muted-foreground';
    const formatTokens = (value: number) => Math.max(0, value).toLocaleString();

    return (
      <div className={cn('px-0 pt-0.5 pb-2', inputOuterClassName)}>
        <div
          className={cn(
            'mx-auto w-full max-w-3xl space-y-2',
            inputInnerClassName
          )}
        >
          <PromptInput
            accept={SUPPORTED_PROMPT_ATTACHMENT_ACCEPT}
            globalDrop
            multiple
            onError={(error) => toast.error(getPromptAttachmentErrorMessage(error))}
            onSubmit={onSubmit}
          >
            <PromptInputBody>
              <PromptInputTextarea
                value={input}
                onChange={(event) => onInputChange(event.target.value)}
                placeholder={placeholder}
              />
            </PromptInputBody>
            <PromptInputFooter>
              <PromptInputTools>
                <PromptInputActionMenu>
                  <PromptInputActionMenuTrigger />
                  <PromptInputActionMenuContent>
                    <PromptInputActionAddAttachments label={attachmentsLabel} />
                  </PromptInputActionMenuContent>
                </PromptInputActionMenu>
              </PromptInputTools>
              <PromptInputTools>
                <PromptInputSubmit
                  onStop={onStopGenerating}
                  status={chatStatus}
                />
              </PromptInputTools>
            </PromptInputFooter>
          </PromptInput>
          {hasTokenUsage && (
            <div className="px-1 text-xs text-muted-foreground">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className={warningToneClass}>
                  上下文: {formatTokens(latestInputTokens)} /{' '}
                  {formatTokens(contextWindowTokens)} ({ratioPercentText})
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }
);

ThreadChatInputPanel.displayName = 'ThreadChatInputPanel';
