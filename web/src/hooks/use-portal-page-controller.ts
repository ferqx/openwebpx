import { type ComponentProps, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { type PromptInputMessage } from '@/components/ai-elements/prompt-input';
import { taskAgentConfig } from '@/lib/agent-config';
import { client } from '@/lib/langgraph-sdk';
import { startSandboxThreadBootstrap } from '@/lib/sandbox';
import { mapThreadToTaskItem, type TaskItem } from '@/lib/tasks';
import { usePortalScmState } from '@/hooks/use-portal-scm-state';
import { usePortalTaskState } from '@/hooks/use-portal-task-state';
import { useAuth } from '@/provider/auth';
import { useThreads } from '@/provider/thread';
import { CreateEnvironmentDialog } from '@/business/portal/create-environment-dialog';
import { PortalDeleteTaskDialog } from '@/business/portal/portal-delete-task-dialog';
import { PortalPromptPanel } from '@/business/portal/portal-prompt-panel';
import { PortalTaskContent } from '@/business/portal/portal-task-content';
import { PortalTaskToolbar } from '@/business/portal/portal-task-toolbar';
import { ScmOauthDialog } from '@/business/portal/scm-oauth-dialog';
import {
  type PortalRouteState,
  type PortalTab
} from '@/business/portal/types';
import { toast } from 'sonner';

export type PortalPageController = {
  tab: PortalTab;
  onTabChange: (tab: PortalTab) => void;
  onLogoClick: () => void;
  onSettingsClick: () => void;
  onLogout: () => void;
  promptPanelProps: ComponentProps<typeof PortalPromptPanel>;
  taskToolbarProps: ComponentProps<typeof PortalTaskToolbar>;
  taskContentProps: ComponentProps<typeof PortalTaskContent>;
  deleteTaskDialogProps: ComponentProps<typeof PortalDeleteTaskDialog>;
  scmOauthDialogProps: ComponentProps<typeof ScmOauthDialog>;
  createEnvironmentDialogProps: ComponentProps<typeof CreateEnvironmentDialog>;
};

export function usePortalPageController(): PortalPageController {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout } = useAuth();
  const {
    threads,
    getThreads,
    deleteThread,
    cancelThreadRun,
    threadsLoading
  } = useThreads();

  const routePortalTab = useMemo(() => {
    const value = (location.state as PortalRouteState | null)?.portalTab;
    if (value === 'tasks' || value === 'review') {
      return value;
    }
    return undefined;
  }, [location.state]);

  const [prompt, setPrompt] = useState('');
  const [tab, setTab] = useState<PortalTab>(() => routePortalTab ?? 'tasks');
  const [isCreatingTask, setIsCreatingTask] = useState(false);

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
    hash: location.hash,
    navigate
  });

  useEffect(() => {
    if (!routePortalTab) return;
    setTab(routePortalTab);
  }, [routePortalTab]);

  const handlePromptSubmit = async ({ text }: PromptInputMessage) => {
    const trimmedText = text.trim();
    if (!trimmedText || isCreatingTask) return;
    if (!scmState.validatedSelectedRepo) {
      toast.info('请选择仓库后再发送');
      return;
    }
    if (!scmState.validatedSelectedBranch) {
      toast.info('请选择分支后再发送');
      return;
    }
    const fallbackScmSource = scmState.authorizedScmSources[0];
    const taskProvider =
      scmState.selectedRepositoryProvider ?? fallbackScmSource?.provider ?? 'github';
    const taskGitlabBaseUrl =
      taskProvider === 'gitlab_enterprise'
        ? (scmState.selectedRepositoryProvider === 'gitlab_enterprise'
          ? scmState.selectedRepositoryGitlabBaseUrl
          : fallbackScmSource?.gitlabBaseUrl)
        : undefined;

    try {
      setIsCreatingTask(true);
      const thread = await client.threads.create({
        metadata: {
          name: trimmedText,
          prompt: trimmedText,
          repo: scmState.validatedSelectedRepo,
          branch: scmState.validatedSelectedBranch,
          model: scmState.selectedModel,
          provider: taskProvider,
          github_auth_mode: taskProvider === 'github' ? 'github_app' : undefined,
          gitlab_base_url: taskGitlabBaseUrl,
          graph_id: taskAgentConfig.graphId
        }
      });

      const autoRunStorageKey = `task:auto-run:${thread.thread_id}`;
      let bootstrapAccepted = false;
      try {
        const bootstrapResult = await startSandboxThreadBootstrap(
          thread.thread_id,
          {
            message: trimmedText,
            stream_mode: ['messages-tuple']
          }
        );
        bootstrapAccepted = bootstrapResult.accepted !== false;
        if (typeof window !== 'undefined' && bootstrapAccepted) {
          window.sessionStorage.setItem(autoRunStorageKey, '1');
        }
        if (bootstrapResult.status === 'error') {
          if (typeof window !== 'undefined') {
            window.sessionStorage.removeItem(autoRunStorageKey);
          }
          toast.error(
            bootstrapResult.error?.trim() ||
              '环境初始化失败，请在任务详情页重试'
          );
        }
      } catch (bootstrapError) {
        if (typeof window !== 'undefined') {
          window.sessionStorage.removeItem(autoRunStorageKey);
        }
        console.error(
          'Failed to start bootstrap from portal prompt submit',
          bootstrapError
        );
      }

      await getThreads();
      setPrompt('');
      navigate(`/tasks/${thread.thread_id}`, {
        state: {
          task: mapThreadToTaskItem(thread),
          initialPrompt: trimmedText,
          shouldAutoRun: true,
          portalTab: tab
        }
      });
    } catch (error) {
      console.error('Failed to create task from portal prompt', error);
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

  const taskToolbarProps: ComponentProps<typeof PortalTaskToolbar> = {
    tab,
    taskSearchOpen: taskState.taskSearchOpen,
    onTaskSearchOpenChange: taskState.setTaskSearchOpen,
    taskQuery: taskState.taskQuery,
    onTaskQueryChange: taskState.setTaskQuery,
    isTasksLoading: taskState.isTasksLoading,
    visibleTasks: taskState.visibleTasks,
    onTaskSelect: handleTaskSelect
  };

  const taskContentProps: ComponentProps<typeof PortalTaskContent> = {
    visibleTasks: taskState.visibleTasks,
    isTasksLoading: taskState.isTasksLoading,
    autoCodeReview: scmState.autoCodeReview,
    onTaskClick: handleTaskClick,
    onTaskDelete: taskState.setPendingDeleteTask,
    onTaskCancelRun: taskState.handleCancelTaskRun,
    cancellingTaskId: taskState.cancellingTaskId,
    onOpenReviewSettings: () => navigate('/settings')
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

  const createEnvironmentDialogProps: ComponentProps<
    typeof CreateEnvironmentDialog
  > = {
    open: scmState.createDialogOpen,
    onOpenChange: scmState.setCreateDialogOpen,
    orgs: scmState.orgs,
    selectedOrg: scmState.selectedOrg,
    onSelectedOrgChange: (value) => {
      scmState.setSelectedOrg(value);
      scmState.setSelectedEnvRepo('');
    },
    envRepoSearchId: scmState.envRepoSearchId,
    envRepoQuery: scmState.envRepoQuery,
    onEnvRepoQueryChange: scmState.setEnvRepoQuery,
    filteredEnvRepos: scmState.filteredEnvRepos,
    selectedEnvRepo: scmState.selectedEnvRepo,
    onSelectedEnvRepoChange: scmState.setSelectedEnvRepo,
    autoCodeReview: scmState.autoCodeReview,
    onAutoCodeReviewChange: scmState.setAutoCodeReview,
    networkAccess: scmState.networkAccess,
    onNetworkAccessChange: scmState.setNetworkAccess,
    onCreate: () => {
      void scmState.handleCreateEnvironment();
    }
  };

  return {
    tab,
    onTabChange: handleTabChange,
    onLogoClick: () => navigate('/'),
    onSettingsClick: () => navigate('/settings'),
    onLogout: () => {
      void logout();
      navigate('/login', { replace: true });
    },
    promptPanelProps,
    taskToolbarProps,
    taskContentProps,
    deleteTaskDialogProps,
    scmOauthDialogProps,
    createEnvironmentDialogProps
  };
}
