import { type ComponentProps, useMemo, useState } from 'react';
import { type NavigateFunction } from 'react-router-dom';
import { toast } from 'sonner';
import {
  buildContinueFixPrompt,
  DEFAULT_CONTINUE_FIX_INSTRUCTION,
  deriveContinueFixTaskOptions,
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
  const [continueFixRunId, setContinueFixRunId] = useState<number | null>(null);
  const [continueFixTaskId, setContinueFixTaskId] = useState('');
  const [continueFixInstruction, setContinueFixInstruction] = useState(
    DEFAULT_CONTINUE_FIX_INSTRUCTION
  );

  const continueFixRun = useMemo(
    () =>
      continueFixRunId === null || selectedRun?.id !== continueFixRunId
        ? null
        : selectedRun,
    [continueFixRunId, selectedRun]
  );
  const continueFixTaskOptions = useMemo(
    () => deriveContinueFixTaskOptions(tasks, selectedRun),
    [selectedRun, tasks]
  );
  const canContinueCodeReviewFix = continueFixTaskOptions.length > 0;
  const continueCodeReviewFixHint = canContinueCodeReviewFix
    ? '会把 findings 整理成新提问并追加到同仓库线程。'
    : '当前仓库还没有可继续的线程。';

  const handleOpenContinueFix = (run: CodeReviewRunDetail) => {
    const nextOptions = deriveContinueFixTaskOptions(tasks, run);
    setContinueFixRunId(run.id);
    setContinueFixTaskId(nextOptions[0]?.id ?? '');
    setContinueFixInstruction(DEFAULT_CONTINUE_FIX_INSTRUCTION);
    setContinueFixOpen(true);
  };

  const handleSubmitContinueFix = async () => {
    if (continueFixRun === null || !continueFixTaskId.trim() || isContinueFixSubmitting) {
      return;
    }
    const targetTask = tasks.find((task) => task.id === continueFixTaskId) ?? null;
    if (targetTask === null) {
      toast.error('未找到目标线程，请重新选择');
      return;
    }

    try {
      setIsContinueFixSubmitting(true);
      const prompt = buildContinueFixPrompt({
        run: continueFixRun,
        instruction: continueFixInstruction
      });
      navigate(`/tasks/${targetTask.id}`, {
        state: {
          task: targetTask,
          initialPrompt: prompt,
          shouldAutoRun: true,
          portalTab: tab
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
    onOpenChange: setContinueFixOpen,
    run: continueFixRun,
    tasks,
    selectedTaskId: continueFixTaskId,
    onSelectedTaskIdChange: setContinueFixTaskId,
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
    canContinueCodeReviewFix,
    continueCodeReviewFixHint,
    handleOpenContinueFix,
    codeReviewContinueFixDialogProps
  };
};
