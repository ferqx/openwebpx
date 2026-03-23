import { type ComponentProps, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { type PromptInputMessage } from '@/components/ai-elements/prompt-input';
import { taskAgentConfig } from '@/lib/agent-config';
import { client } from '@/lib/langgraph-sdk';
import { startSandboxThreadBootstrap } from '@/lib/sandbox';
import { mapThreadToTaskItem, type TaskItem } from '@/lib/tasks';
import {
  type CodeReviewRepositoryConfig,
  getCodeReviewRepositoryConfig,
  updateCodeReviewRepositoryConfig
} from '@/lib/code-review';
import { usePortalScmState } from '@/hooks/use-portal-scm-state';
import { usePortalCodeReviewContinuation } from '@/hooks/use-portal-code-review-continuation';
import {
  matchesCodeReviewRepositoryContext,
  usePortalCodeReviewState
} from '@/hooks/use-portal-code-review-state';
import { usePortalTaskState } from '@/hooks/use-portal-task-state';
import { useAuth } from '@/provider/auth';
import { useThreads } from '@/provider/thread';
import { CreateEnvironmentDialog } from '@/business/portal/create-environment-dialog';
import { PortalCodeReviewContinueFixDialog } from '@/business/portal/portal-code-review-continue-fix-dialog';
import { PortalCodeReviewSettingsSheet } from '@/business/portal/portal-code-review-settings-sheet';
import { PortalDeleteTaskDialog } from '@/business/portal/portal-delete-task-dialog';
import { PortalPromptPanel } from '@/business/portal/portal-prompt-panel';
import { PortalTaskContent } from '@/business/portal/portal-task-content';
import { PortalTaskToolbar } from '@/business/portal/portal-task-toolbar';
import { ScmOauthDialog } from '@/business/portal/scm-oauth-dialog';
import {
  type PortalRouteState,
  resolvePortalRouteTab,
  type PortalTab
} from '@/business/portal/types';
import { toast } from 'sonner';

const isCodeReviewRepositoryAuthorized = (
  repository: {
    id: number;
    provider: 'github' | 'gitlab';
    gitlab_base_url?: string | null;
  },
  authorizedSources: Array<{
    provider: 'github' | 'gitlab' | 'gitlab_enterprise';
    gitlabBaseUrl?: string;
  }>
) => {
  return authorizedSources.some((source) => {
    if (repository.provider === 'github') {
      return source.provider === 'github';
    }
    if (source.provider === 'gitlab') {
      return true;
    }
    if (source.provider === 'gitlab_enterprise') {
      const sourceBaseUrl = source.gitlabBaseUrl?.trim().toLowerCase() ?? '';
      const repositoryBaseUrl =
        repository.gitlab_base_url?.trim().toLowerCase() ?? '';
      return sourceBaseUrl.length > 0 && sourceBaseUrl === repositoryBaseUrl;
    }
    return false;
  });
};

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
  createEnvironmentDialogProps: ComponentProps<typeof CreateEnvironmentDialog>;
  codeReviewSettingsSheetProps: ComponentProps<
    typeof PortalCodeReviewSettingsSheet
  >;
  codeReviewContinueFixDialogProps: ComponentProps<
    typeof PortalCodeReviewContinueFixDialog
  >;
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
    return resolvePortalRouteTab(value);
  }, [location.state]);

  const [prompt, setPrompt] = useState('');
  const [tab, setTab] = useState<PortalTab>(() => routePortalTab ?? 'tasks');
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [reviewSettingsOpen, setReviewSettingsOpen] = useState(false);
  const [isReviewSettingsLoading, setIsReviewSettingsLoading] = useState(false);
  const [isReviewSettingsSaving, setIsReviewSettingsSaving] = useState(false);
  const [selectedReviewSettingsRepositoryId, setSelectedReviewSettingsRepositoryId] =
    useState<number | null>(null);
  const [reviewSettingsConfigsByRepositoryId, setReviewSettingsConfigsByRepositoryId] =
    useState<Record<number, CodeReviewRepositoryConfig>>({});
  const [reviewConfigDraft, setReviewConfigDraft] = useState({
    review_enabled: false,
    review_triggers: null,
    auto_fix_enabled: false,
    auto_fix_severities: null,
    auto_fix_requires_approval: true,
    auto_publish_enabled: false
  });

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
  const selectedCodeReviewRepository = useMemo(
    () =>
      codeReviewState.repositories.find((repository) =>
        matchesCodeReviewRepositoryContext(repository, {
          selectedRepo: scmState.validatedSelectedRepo,
          selectedProvider: scmState.selectedRepositoryProvider,
          selectedGitlabBaseUrl: scmState.selectedRepositoryGitlabBaseUrl
        })
      ) ?? null,
    [
      codeReviewState.repositories,
      scmState.selectedRepositoryGitlabBaseUrl,
      scmState.selectedRepositoryProvider,
      scmState.validatedSelectedRepo
    ]
  );
  const authorizedCodeReviewRepositories = useMemo(
    () =>
      codeReviewState.repositories.filter((repository) =>
        isCodeReviewRepositoryAuthorized(
          repository,
          scmState.authorizedScmSources
        )
      ),
    [codeReviewState.repositories, scmState.authorizedScmSources]
  );
  const enabledCodeReviewRepositoryIds = useMemo(
    () =>
      new Set(
        Object.values(reviewSettingsConfigsByRepositoryId)
          .filter((config) => config.review_enabled)
          .map((config) => config.repository_integration_id)
      ),
    [reviewSettingsConfigsByRepositoryId]
  );
  const selectedReviewSettingsRepository = useMemo(() => {
    const repository =
      authorizedCodeReviewRepositories.find(
        (item) => item.id === selectedReviewSettingsRepositoryId
      ) ?? null;
    if (repository !== null) return repository;
    return selectedCodeReviewRepository;
  }, [
    authorizedCodeReviewRepositories,
    selectedCodeReviewRepository,
    selectedReviewSettingsRepositoryId
  ]);

  useEffect(() => {
    if (!reviewSettingsOpen) return;
    if (selectedCodeReviewRepository === null) return;
    setSelectedReviewSettingsRepositoryId(selectedCodeReviewRepository.id);
  }, [reviewSettingsOpen, selectedCodeReviewRepository]);

  useEffect(() => {
    if (!reviewSettingsOpen) return;
    const candidateRepositories = [
      ...authorizedCodeReviewRepositories,
      ...(selectedCodeReviewRepository ? [selectedCodeReviewRepository] : [])
    ].filter(
      (repository, index, collection) =>
        collection.findIndex((item) => item.id === repository.id) === index
    );
    if (candidateRepositories.length === 0) return;

    let cancelled = false;
    void Promise.allSettled(
      candidateRepositories.map(async (repository) => [
        repository.id,
        await getCodeReviewRepositoryConfig(repository.id)
      ] as const)
    ).then((results) => {
      if (cancelled) return;
      const nextConfigs: Record<number, CodeReviewRepositoryConfig> = {};
      for (const result of results) {
        if (result.status !== 'fulfilled') continue;
        const [repositoryId, config] = result.value;
        nextConfigs[repositoryId] = config;
      }
      if (Object.keys(nextConfigs).length === 0) return;
      setReviewSettingsConfigsByRepositoryId((previous) => ({
        ...previous,
        ...nextConfigs
      }));
    });

    return () => {
      cancelled = true;
    };
  }, [
    authorizedCodeReviewRepositories,
    reviewSettingsOpen,
    selectedCodeReviewRepository
  ]);

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

  const handleReviewSettingsClick = () => {
    setReviewSettingsOpen(true);
  };

  useEffect(() => {
    if (!reviewSettingsOpen) return;
    if (selectedReviewSettingsRepository === null) return;

    const cachedConfig =
      reviewSettingsConfigsByRepositoryId[selectedReviewSettingsRepository.id];
    if (cachedConfig) {
      setReviewConfigDraft({
        review_enabled: cachedConfig.review_enabled,
        review_triggers: cachedConfig.review_triggers,
        auto_fix_enabled: cachedConfig.auto_fix_enabled,
        auto_fix_severities: cachedConfig.auto_fix_severities,
        auto_fix_requires_approval: cachedConfig.auto_fix_requires_approval,
        auto_publish_enabled: cachedConfig.auto_publish_enabled
      });
      setIsReviewSettingsLoading(false);
      return;
    }

    let cancelled = false;
    setIsReviewSettingsLoading(true);
    void getCodeReviewRepositoryConfig(selectedReviewSettingsRepository.id)
      .then((config) => {
        if (cancelled) return;
        setReviewSettingsConfigsByRepositoryId((previous) => ({
          ...previous,
          [selectedReviewSettingsRepository.id]: config
        }));
        setReviewConfigDraft({
          review_enabled: config.review_enabled,
          review_triggers: config.review_triggers,
          auto_fix_enabled: config.auto_fix_enabled,
          auto_fix_severities: config.auto_fix_severities,
          auto_fix_requires_approval: config.auto_fix_requires_approval,
          auto_publish_enabled: config.auto_publish_enabled
        });
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Failed to load code review repository config', error);
        toast.error('加载审查设置失败，请稍后重试');
      })
      .finally(() => {
        if (!cancelled) {
          setIsReviewSettingsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [
    reviewSettingsConfigsByRepositoryId,
    reviewSettingsOpen,
    selectedReviewSettingsRepository
  ]);

  const handleSaveReviewSettings = async () => {
    if (selectedReviewSettingsRepository === null || isReviewSettingsSaving) return;
    try {
      setIsReviewSettingsSaving(true);
      const config = await updateCodeReviewRepositoryConfig(
        selectedReviewSettingsRepository.id,
        reviewConfigDraft
      );
      setReviewSettingsConfigsByRepositoryId((previous) => ({
        ...previous,
        [selectedReviewSettingsRepository.id]: config
      }));
      setReviewConfigDraft({
        review_enabled: config.review_enabled,
        review_triggers: config.review_triggers,
        auto_fix_enabled: config.auto_fix_enabled,
        auto_fix_severities: config.auto_fix_severities,
        auto_fix_requires_approval: config.auto_fix_requires_approval,
        auto_publish_enabled: config.auto_publish_enabled
      });
      toast.success('审查设置已保存');
      await codeReviewState.refresh();
      setReviewSettingsOpen(false);
    } catch (error) {
      console.error('Failed to save code review repository config', error);
      toast.error('保存审查设置失败，请稍后重试');
    } finally {
      setIsReviewSettingsSaving(false);
    }
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
    onTaskSelect: handleTaskSelect,
    onReviewSettingsClick: handleReviewSettingsClick
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
      onSelectRun: (runId) => codeReviewState.setSelectedRunId(runId),
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
      hasLoadedInitialData: codeReviewState.hasLoadedInitialData
    },
    selectedCodeReviewRunId: codeReviewState.selectedRunId,
    onBackFromCodeReviewDetail: () => codeReviewState.setSelectedRunId(null),
    selectedCodeReviewRun: codeReviewState.selectedRun,
    selectedCodeReviewRunError: codeReviewState.selectedRunError,
    isSelectedCodeReviewRunLoading: codeReviewState.isSelectedRunLoading,
    onRetryCodeReviewRun: () => {
      if (codeReviewState.selectedRunId === null) return;
      void codeReviewState.loadRunDetail(codeReviewState.selectedRunId);
    },
    onPublishCodeReviewRun: (runId) => {
      void codeReviewState.publishRun(runId);
    },
    onContinueCodeReviewFix: (run) => {
      codeReviewContinuation.handleOpenContinueFix(run);
    },
    onApproveCodeReviewFixRequest: (fixRequestId, runId) => {
      void codeReviewState.approveFixRequest(fixRequestId, runId);
    },
    onRejectCodeReviewFixRequest: (fixRequestId, runId) => {
      void codeReviewState.rejectFixRequest(fixRequestId, runId);
    },
    canContinueCodeReviewFix: codeReviewContinuation.canContinueCodeReviewFix,
    continueCodeReviewFixHint: codeReviewContinuation.continueCodeReviewFixHint,
    publishingCodeReviewRunIds: codeReviewState.publishingRunIds,
    approvingCodeReviewFixRequestIds: codeReviewState.approvingFixRequestIds,
    rejectingCodeReviewFixRequestIds: codeReviewState.rejectingFixRequestIds
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
    networkAccess: scmState.networkAccess,
    onNetworkAccessChange: scmState.setNetworkAccess,
    onCreate: () => {
      void scmState.handleCreateEnvironment();
    }
  };

  const codeReviewSettingsSheetProps: ComponentProps<
    typeof PortalCodeReviewSettingsSheet
  > = {
    open: reviewSettingsOpen,
    onOpenChange: setReviewSettingsOpen,
    repositoryName:
      selectedReviewSettingsRepository?.full_name ?? scmState.validatedSelectedRepo,
    hasSelectedRepository: selectedReviewSettingsRepository !== null,
    repositories: authorizedCodeReviewRepositories,
    selectedRepositoryId: selectedReviewSettingsRepository?.id ?? null,
    onSelectRepositoryId: setSelectedReviewSettingsRepositoryId,
    enabledRepositoryIds: enabledCodeReviewRepositoryIds,
    isLoading: isReviewSettingsLoading,
    isSaving: isReviewSettingsSaving,
    draft: reviewConfigDraft,
    onDraftChange: setReviewConfigDraft,
    onSave: handleSaveReviewSettings
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
    createEnvironmentDialogProps,
    codeReviewSettingsSheetProps,
    codeReviewContinueFixDialogProps:
      codeReviewContinuation.codeReviewContinueFixDialogProps
  };
}
