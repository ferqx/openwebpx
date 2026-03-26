import { type ComponentProps, useMemo, useState } from 'react';
import { type NavigateFunction } from 'react-router-dom';
import { toast } from 'sonner';
import {
  buildContinueFixPrompt,
  DEFAULT_CONTINUE_FIX_INSTRUCTION,
  PortalCodeReviewContinueFixDialog,
  resolveContinueFixInstruction
} from '@/business/portal/portal-code-review-continue-fix-dialog';
import { type CodeReviewRunDetail } from '@/business/portal/code-review-types';
import { type PortalTab } from '@/business/portal/types';
import { type TaskItem } from '@/lib/tasks';

type UsePortalCodeReviewContinuationOptions = {
  tasks: TaskItem[];
  selectedRun: CodeReviewRunDetail | null;
  tab: PortalTab;
  navigate: NavigateFunction;
};

export const usePortalCodeReviewContinuation = ({
  tasks,
  selectedRun,
  tab,
  navigate
}: UsePortalCodeReviewContinuationOptions) => {
  const [continueFixOpen, setContinueFixOpen] = useState(false);
  const [isContinueFixSubmitting, setIsContinueFixSubmitting] = useState(false);
  const [continueFixRun, setContinueFixRun] = useState<CodeReviewRunDetail | null>(null);
  const [continueFixInstruction, setContinueFixInstruction] = useState(
    DEFAULT_CONTINUE_FIX_INSTRUCTION
  );

  const continueFixThreadId = continueFixRun?.thread_id?.trim() ?? '';
  const continueFixTask = useMemo(
    () => (continueFixThreadId ? tasks.find((task) => task.id === continueFixThreadId) ?? null : null),
    [continueFixThreadId, tasks]
  );
  const canContinueCodeReviewFixState = Boolean(selectedRun?.thread_id?.trim());
  const continueCodeReviewFixHint = canContinueCodeReviewFixState
    ? '会把 findings 整理成新提问并追加到审查绑定的唯一线程。'
    : '当前审查没有绑定线程，无法继续修复。';

  const handleOpenContinueFix = (run: CodeReviewRunDetail) => {
    setContinueFixRun(run);
    setContinueFixInstruction(DEFAULT_CONTINUE_FIX_INSTRUCTION);
    setContinueFixOpen(true);
  };

  const handleSubmitContinueFix = async () => {
    if (continueFixRun === null || !continueFixThreadId || isContinueFixSubmitting) {
      return;
    }
    const targetTask = continueFixTask;

    try {
      setIsContinueFixSubmitting(true);
      const prompt = buildContinueFixPrompt({
        run: continueFixRun,
        instruction: continueFixInstruction
      });
      navigate(`/tasks/${continueFixThreadId}`, {
        state: {
          initialPrompt: prompt,
          shouldAutoRun: true,
          portalTab: tab,
          ...(targetTask ? { task: targetTask } : {})
        }
      });
      setContinueFixOpen(false);
    } catch (error) {
      console.error('Failed to continue code review fixes in thread', error);
      toast.error('发送修复请求到线程失败，请稍后重试');
    } finally {
      setIsContinueFixSubmitting(false);
    }
  };

  const codeReviewContinueFixDialogProps: ComponentProps<
    typeof PortalCodeReviewContinueFixDialog
  > = {
    open: continueFixOpen,
    onOpenChange: (open) => {
      setContinueFixOpen(open);
      if (!open) {
        setContinueFixRun(null);
      }
    },
    run: continueFixRun,
    threadId: continueFixRun?.thread_id?.trim() ?? null,
    threadTask: continueFixTask,
    instruction: continueFixInstruction,
    onInstructionChange: setContinueFixInstruction,
    onInstructionTemplateChange: (templateId) => {
      const templateInstruction = resolveContinueFixInstruction(templateId);
      if (!templateInstruction) return;
      setContinueFixInstruction(templateInstruction);
    },
    isSubmitting: isContinueFixSubmitting,
    onSubmit: handleSubmitContinueFix
  };

  return {
    canContinueCodeReviewFix: canContinueCodeReviewFixState,
    continueCodeReviewFixHint,
    handleOpenContinueFix,
    codeReviewContinueFixDialogProps
  };
};
