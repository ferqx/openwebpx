import { useEffect, useState, type ComponentProps } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { type PromptInputMessage } from '@/components/ai-elements/prompt-input';
import { type TaskItem } from '@/lib/tasks';
import { useAuth } from '@/provider/auth';
import { useThreads } from '@/provider/thread';

import { PortalCodeReviewContinueFixDialog } from '@/business/portal/portal-code-review-continue-fix-dialog';
import { PortalDeleteTaskDialog } from '@/business/portal/portal-delete-task-dialog';
import { PortalPromptPanel } from '@/business/portal/portal-prompt-panel';
import { PortalTaskContent } from '@/business/portal/portal-task-content';
import { PortalTaskToolbar } from '@/business/portal/portal-task-toolbar';
import { resolvePortalRouteTab, type PortalTab } from '@/business/portal/types';
import { ScmOauthDialog } from '@/business/portal/scm-oauth-dialog';
import { usePortalCodeReviewContinuation } from '@/hooks/use-portal-code-review-continuation';
import {
  usePortalCodeReviewState
} from '@/hooks/use-portal-code-review-state';
import { usePortalScmState } from '@/hooks/use-portal-scm-state';
import { usePortalTaskState } from '@/hooks/use-portal-task-state';

export type PortalPageController = {
  tab: PortalTab;
  onTabChange: (tab: PortalTab) => void;
  onLogoClick: () => void;
  onSettingsClick: () => void;
  onReviewSettingsClick: () => void;
  onLogout: () => void;
  promptPanelProps: ComponentProps<typeof PortalPromptPanel>;
  taskToolbarProps: ComponentProps<typeof PortalTaskToolbar>;
  taskContentProps: ComponentProps<typeof PortalTaskContent>;
  deleteTaskDialogProps: ComponentProps<typeof PortalDeleteTaskDialog>;
  scmOauthDialogProps: ComponentProps<typeof ScmOauthDialog>;
  codeReviewContinueFixDialogProps: ComponentProps<
    typeof PortalCodeReviewContinueFixDialog
  >;
};

export const usePortalPageController = (): PortalPageController => {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [tab, setTab] = useState<PortalTab>('tasks');
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [prompt, setPrompt] = useState('');

  const { threads, getThreads, threadsLoading, deleteThread, cancelThreadRun, createThread } =
    useThreads();

  const taskState = usePortalTaskState({
    threads,
    threadsLoading,
    getThreads,
    deleteThread,
    cancelThreadRun
  });

  const scmState = usePortalScmState({
    pathname: location.pathname,
    search: location.search,
    hash: location.hash
  });

  const codeReviewState = usePortalCodeReviewState({
    selectedRepo: scmState.validatedSelectedRepo,
    selectedProvider: scmState.selectedRepositoryProvider,
    selectedGitlabBaseUrl: scmState.selectedRepositoryGitlabBaseUrl,
    enabled: tab === 'review'
  });

  const codeReviewContinuation = usePortalCodeReviewContinuation({
    tasks: taskState.tasks,
    selectedRun: codeReviewState.selectedRun,
    tab,
    navigate
  });

  useEffect(() => {
    const routeTab = resolvePortalRouteTab(
      (location.state as { portalTab?: unknown } | null)?.portalTab
    );
    if (routeTab) {
      setTab(routeTab);
    }
  }, [location.state]);

  const handlePromptSubmit = async (message: PromptInputMessage) => {
    if (isCreatingTask) return;
    try {
      setIsCreatingTask(true);
      const thread = await createThread(message.text);
      navigate(`/tasks/${thread.thread_id}`, {
        state: {
          shouldAutoRun: true,
          prompt: message.text,
          attachments: message.files,
          task: {
            id: thread.thread_id,
            title: message.text,
            status: 'starting',
            updatedAt: new Date().toISOString(),
            repo: scmState.validatedSelectedRepo,
            branch: scmState.validatedSelectedBranch
          }
        }
      });
      setPrompt('');
    } catch (error) {
      console.error('Failed to create task', error);
      toast.error('创建任务失败，请稍后重试');
    } finally {
      setIsCreatingTask(false);
    }
  };

  const handleTaskClick = (item: TaskItem) => {
    navigate(`/tasks/${item.id}`, { state: { task: item, portalTab: tab } });
  };

  const handleTaskSelect = (item: TaskItem) => {
    handleTaskClick(item);
    taskState.setTaskSearchOpen(false);
  };

  const handleTabChange = (nextTab: PortalTab) => {
    setTab(nextTab);
    taskState.setTaskSearchOpen(false);
  };

  const handleReviewSettingsClick = () => {
    navigate('/settings?tab=code-review');
  };

  const promptPanelProps: ComponentProps<typeof PortalPromptPanel> = {
    prompt,
    onPromptChange: setPrompt,
    onSubmit: handlePromptSubmit,
    isCreatingTask,
    selectedRepoKey: scmState.selectedRepoKey,
    selectedRepo: scmState.validatedSelectedRepo,
    repositoryOptions: scmState.repositoryOptions,
    isRepositoryLoading: scmState.isRepositoryLoading,
    repositoryEmptyMessage: scmState.repositoryEmptyMessage,
    onSelectRepoKey: scmState.setSelectedRepoKey,
    selectedBranch: scmState.validatedSelectedBranch,
    branchOptions: scmState.branchOptions,
    isBranchLoading: scmState.isBranchLoading,
    onSelectBranch: scmState.setSelectedBranch,
    selectedModel: scmState.selectedModel,
    models: scmState.models,
    onSelectModel: scmState.setSelectedModel,
    onOpenScmAuthDialog: () => scmState.setScmOauthDialogOpen(true),
    onRefreshRepositories: scmState.handleRefreshRepositories
  };

  const handleReviewRepoFilterSelect = (key: string) => {
    scmState.setSelectedRepoKey(key);
  };

  const handleClearReviewRepoFilter = () => {
    scmState.setSelectedRepoKey('');
  };

  const taskToolbarProps: ComponentProps<typeof PortalTaskToolbar> = {
    tab,
    taskSearchOpen: taskState.taskSearchOpen,
    onTaskSearchOpenChange: taskState.setTaskSearchOpen,
    taskQuery: taskState.taskQuery,
    onTaskQueryChange: taskState.setTaskQuery,
    isTasksLoading: taskState.isTasksLoading,
    visibleTasks: taskState.visibleTasks,
    onTaskSelect: handleTaskSelect,
    onReviewSettingsClick: handleReviewSettingsClick,
    reviewRepoOptions: scmState.repositoryOptions,
    selectedReviewRepoKey: scmState.selectedRepoKey,
    onReviewRepoSelect: handleReviewRepoFilterSelect,
    onReviewRepoClear: handleClearReviewRepoFilter
  };

  const taskContentProps: ComponentProps<typeof PortalTaskContent> = {
    visibleTasks: taskState.visibleTasks,
    isTasksLoading: taskState.isTasksLoading,
    onTaskClick: handleTaskClick,
    onTaskDelete: taskState.setPendingDeleteTask,
    onTaskCancelRun: taskState.handleCancelTaskRun,
    cancellingTaskId: taskState.cancellingTaskId,
    codeReviewListProps: {
      visibleRuns: codeReviewState.visibleRuns,
      selectedRunId: codeReviewState.selectedRunId,
      onSelectRun: (runId: number) => {
        navigate(`/reviews/${runId}`, {
          state: {
            portalTab: 'review'
          }
        });
      },
      isLoading: !codeReviewState.hasLoadedInitialData,
      isRefreshing: codeReviewState.isRefreshing,
      emptyStateMessage: codeReviewState.emptyStateMessage,
      searchQuery: codeReviewState.searchQuery,
      onSearchQueryChange: codeReviewState.setSearchQuery,
      statusFilter: codeReviewState.statusFilter,
      onStatusFilterChange: codeReviewState.setStatusFilter,
      modeFilter: codeReviewState.modeFilter,
      onModeFilterChange: codeReviewState.setModeFilter,
      pendingApprovalCount: codeReviewState.pendingApprovalCount,
      onPublishCodeReviewRun: codeReviewState.publishRun,
      onContinueCodeReviewFix: codeReviewContinuation.handleOpenContinueFix,
      onApproveCodeReviewFixRequest: codeReviewState.approveFixRequest,
      onRejectCodeReviewFixRequest: codeReviewState.rejectFixRequest,
      canContinueCodeReviewFix: codeReviewContinuation.canContinueCodeReviewFix,
      continueCodeReviewFixHint: codeReviewContinuation.continueCodeReviewFixHint,
      publishingCodeReviewRunIds: codeReviewState.publishingRunIds,
      approvingCodeReviewFixRequestIds: codeReviewState.approvingFixRequestIds,
      rejectingCodeReviewFixRequestIds: codeReviewState.rejectingFixRequestIds
    }
  };

  const deleteTaskDialogProps: ComponentProps<typeof PortalDeleteTaskDialog> = {
    open: Boolean(taskState.pendingDeleteTask),
    taskTitle: taskState.pendingDeleteTask?.title,
    isDeleting: taskState.isDeletingTask,
    onOpenChange: (open) => {
      if (!open && !taskState.isDeletingTask) {
        taskState.setPendingDeleteTask(null);
      }
    },
    onConfirm: () => {
      void taskState.handleDeleteTask();
    }
  };

  const scmOauthDialogProps: ComponentProps<typeof ScmOauthDialog> = {
    open: scmState.scmOauthDialogOpen,
    onOpenChange: scmState.setScmOauthDialogOpen,
    provider: scmState.authDialogProvider,
    onProviderChange: scmState.setAuthDialogProvider,
    gitlabBaseUrl: scmState.authDialogGitlabBaseUrl,
    onGitlabBaseUrlChange: scmState.setAuthDialogGitlabBaseUrl,
    isAuthorizing: scmState.isAuthorizingScm,
    onAuthorize: scmState.handleAuthorizeScm,
    connectedSources: scmState.authorizedScmSources,
    isConnectionsLoading: scmState.isScmConnectionsLoading,
    revokingSourceKey: scmState.revokingScmSourceKey,
    canRevokeSource: !scmState.isScmConnectionsApiUnavailable,
    onRevokeSource: (source) => {
      void scmState.handleRevokeScmSource(source);
    }
  };

  return {
    tab,
    onTabChange: handleTabChange,
    onLogoClick: () => navigate('/'),
    onSettingsClick: () => navigate('/settings'),
    onReviewSettingsClick: handleReviewSettingsClick,
    onLogout: () => {
      void logout();
      navigate('/login', { replace: true });
    },
    promptPanelProps,
    taskToolbarProps,
    taskContentProps,
    deleteTaskDialogProps,
    scmOauthDialogProps,
    codeReviewContinueFixDialogProps:
      codeReviewContinuation.codeReviewContinueFixDialogProps
  };
};
