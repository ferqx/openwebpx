import { ArrowUp } from 'lucide-react';
import {
  PromptInput,
  PromptInputActionAddAttachments,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuTrigger,
  PromptInputBody,
  type PromptInputMessage,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  PromptInputProvider
} from '@/components/ai-elements/prompt-input';
import {
  SUPPORTED_PROMPT_ATTACHMENT_ACCEPT,
  getPromptAttachmentErrorMessage
} from '@/lib/prompt-input-attachments';
import { toast } from 'sonner';
import { PortalBranchPicker } from '@/business/portal/portal-branch-picker';
import { PortalRepoPicker } from '@/business/portal/portal-repo-picker';
import { type PortalScmRepositoryOption } from '@/business/portal/types';

type PortalPromptPanelProps = {
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: (message: PromptInputMessage) => void | Promise<void>;
  isCreatingTask: boolean;
  selectedRepoKey: string;
  selectedRepo: string;
  repositoryOptions: PortalScmRepositoryOption[];
  isRepositoryLoading: boolean;
  repositoryEmptyMessage: string;
  onSelectRepoKey: (key: string) => void;
  selectedBranch: string;
  branchOptions: string[];
  isBranchLoading: boolean;
  onSelectBranch: (branch: string) => void;
  selectedModel: string;
  models: string[];
  onSelectModel: (model: string) => void;
  onOpenScmAuthDialog: () => void;
  onRefreshRepositories: () => void;
};

export function PortalPromptPanel({
  prompt,
  onPromptChange,
  onSubmit,
  isCreatingTask,
  selectedRepoKey,
  selectedRepo,
  repositoryOptions,
  isRepositoryLoading,
  repositoryEmptyMessage,
  onSelectRepoKey,
  selectedBranch,
  branchOptions,
  isBranchLoading,
  onSelectBranch,
  onOpenScmAuthDialog,
  onRefreshRepositories
}: PortalPromptPanelProps) {
  const submitDisabledReason = !selectedRepo
    ? '请选择仓库后再发送'
    : !selectedBranch
      ? '请选择分支后再发送'
      : !prompt.trim()
        ? '请输入任务描述'
        : isCreatingTask
          ? '任务创建中...'
          : '';

  return (
    <PromptInputProvider>
      <PromptInput
        accept={SUPPORTED_PROMPT_ATTACHMENT_ACCEPT}
        globalDrop
        multiple
        onError={(error) => toast.error(getPromptAttachmentErrorMessage(error))}
        onSubmit={onSubmit}
      >
        <PromptInputBody>
          <PromptInputTextarea
            className="px-4 py-3"
            placeholder="描述任务"
            value={prompt}
            onChange={(e) => onPromptChange(e.target.value)}
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <PromptInputActionMenu>
              <PromptInputActionMenuTrigger />
              <PromptInputActionMenuContent>
                <PromptInputActionAddAttachments label="添加文件" />
              </PromptInputActionMenuContent>
            </PromptInputActionMenu>

            <PortalRepoPicker
              selectedRepoKey={selectedRepoKey}
              selectedRepo={selectedRepo}
              repositoryOptions={repositoryOptions}
              isRepositoryLoading={isRepositoryLoading}
              repositoryEmptyMessage={repositoryEmptyMessage}
              onSelectRepoKey={onSelectRepoKey}
              onOpenScmAuthDialog={onOpenScmAuthDialog}
              onRefreshRepositories={onRefreshRepositories}
            />

            <PortalBranchPicker
              selectedRepo={selectedRepo}
              selectedBranch={selectedBranch}
              branchOptions={branchOptions}
              isBranchLoading={isBranchLoading}
              onSelectBranch={onSelectBranch}
            />
          </PromptInputTools>

          <PromptInputTools className="items-center gap-2">
            {submitDisabledReason ? (
              <span className="text-muted-foreground text-xs">
                {submitDisabledReason}
              </span>
            ) : null}
            <PromptInputSubmit disabled={Boolean(submitDisabledReason)}>
              <ArrowUp />
            </PromptInputSubmit>
          </PromptInputTools>
        </PromptInputFooter>
      </PromptInput>
    </PromptInputProvider>
  );
}
