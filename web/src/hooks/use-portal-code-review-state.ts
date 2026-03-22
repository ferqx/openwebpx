import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  approveCodeReviewFixRequest,
  getCodeReviewRun,
  listCodeReviewRepositories,
  listCodeReviewRuns,
  publishCodeReviewRun,
  rejectCodeReviewFixRequest,
  syncCodeReviewRepositories
} from '@/lib/code-review';
import { normalizeGitlabBaseUrl } from '@/lib/scm-domain';
import { type ScmProvider } from '@/lib/scm';
import {
  type CodeReviewFixRequestStatus,
  type CodeReviewRepositorySummary,
  type CodeReviewRunDetail,
  type CodeReviewRunStatus,
  type CodeReviewRunSummary,
  type CodeReviewTimelineEvent
} from '@/business/portal/code-review-types';

export type PortalCodeReviewStatusFilter = 'all' | CodeReviewRunStatus;
export type PortalCodeReviewMode = 'review_only' | 'auto_fix_enabled' | 'pending_approval';
export type PortalCodeReviewModeFilter = 'all' | PortalCodeReviewMode;

export type PortalCodeReviewContext = {
  selectedRepo: string;
  selectedProvider?: ScmProvider;
  selectedGitlabBaseUrl?: string;
};

export type PortalCodeReviewRunItem = CodeReviewRunSummary & {
  repository: CodeReviewRepositorySummary | null;
  repositoryName: string;
  repositoryDefaultBranch: string | null;
  mode: PortalCodeReviewMode | null;
  hasPendingApproval: boolean;
  pendingApprovalCount: number;
  findingsCount: number | null;
  lastEventType: string | null;
};

type UsePortalCodeReviewStateOptions = PortalCodeReviewContext & {
  enabled?: boolean;
};

type LoadPortalCodeReviewSnapshotOptions = {
  listRepositories: typeof listCodeReviewRepositories;
  listRuns: typeof listCodeReviewRuns;
};

type InferredFixRequestState = CodeReviewFixRequestStatus;

const FIX_REQUEST_EVENT_STATE: Record<string, InferredFixRequestState> = {
  fix_request_created: 'pending_approval',
  fix_request_approved: 'approved',
  fix_request_running: 'running',
  fix_request_completed: 'completed',
  fix_request_failed: 'failed',
  fix_request_rejected: 'rejected'
};

const normalizeReviewProvider = (
  provider?: ScmProvider
): 'github' | 'gitlab' | null => {
  if (provider === 'github') return 'github';
  if (provider === 'gitlab' || provider === 'gitlab_enterprise') return 'gitlab';
  return null;
};

export const buildCodeReviewSyncRequest = (context: PortalCodeReviewContext) => {
  const normalizedProvider = normalizeReviewProvider(context.selectedProvider);
  if (normalizedProvider === null) return null;
  return {
    provider: normalizedProvider,
    gitlab_base_url:
      context.selectedProvider === 'gitlab_enterprise'
        ? (context.selectedGitlabBaseUrl?.trim() ?? null)
        : null
  };
};

const getEventFixRequestId = (event: CodeReviewTimelineEvent): number | null => {
  const value = event.payload?.fix_request_id;
  return typeof value === 'number' ? value : null;
};

const getFixRequestStatesFromDetail = (
  detail: CodeReviewRunDetail
): InferredFixRequestState[] => {
  if (detail.fix_requests.length > 0) {
    return detail.fix_requests.map((fixRequest) => fixRequest.status);
  }
  return Array.from(inferFixRequestStates(detail.timeline_events).values());
};

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error instanceof Error && error.message.trim()) {
    return error.message.trim();
  }
  return fallback;
};

export const matchesCodeReviewRepositoryContext = (
  repository: CodeReviewRepositorySummary | null,
  context: PortalCodeReviewContext
) => {
  if (repository === null) return false;
  if (!context.selectedRepo.trim()) return false;
  if ((repository.full_name ?? '').trim() !== context.selectedRepo.trim()) {
    return false;
  }

  const normalizedProvider = normalizeReviewProvider(context.selectedProvider);
  if (normalizedProvider !== null && repository.provider !== normalizedProvider) {
    return false;
  }

  if (
    context.selectedProvider === 'gitlab_enterprise' &&
    context.selectedGitlabBaseUrl?.trim()
  ) {
    const selectedBaseUrl = normalizeGitlabBaseUrl(context.selectedGitlabBaseUrl);
    const repositoryBaseUrl = normalizeGitlabBaseUrl(
      repository.gitlab_base_url ?? ''
    );
    return selectedBaseUrl === repositoryBaseUrl;
  }

  return true;
};

export const inferFixRequestStates = (
  events: CodeReviewTimelineEvent[]
): Map<number, InferredFixRequestState> => {
  const states = new Map<number, InferredFixRequestState>();
  for (const event of events) {
    const nextState = FIX_REQUEST_EVENT_STATE[event.event_type];
    if (!nextState) continue;
    const fixRequestId = getEventFixRequestId(event);
    if (fixRequestId === null) continue;
    states.set(fixRequestId, nextState);
  }
  return states;
};

export const resolvePortalCodeReviewMode = (
  detail: CodeReviewRunDetail | null | undefined
): PortalCodeReviewMode | null => {
  if (!detail) return null;
  const states = getFixRequestStatesFromDetail(detail);
  if (states.includes('pending_approval')) {
    return 'pending_approval';
  }
  if (states.length > 0) {
    return 'auto_fix_enabled';
  }
  return 'review_only';
};

export const getPendingApprovalCount = (
  detail: CodeReviewRunDetail | null | undefined
) => {
  if (!detail) return 0;
  return getFixRequestStatesFromDetail(detail).filter(
    (state) => state === 'pending_approval'
  ).length;
};

const matchesRunSearch = (run: PortalCodeReviewRunItem, query: string) => {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;
  const candidates = [
    run.repositoryName,
    run.external_pr_or_mr_id ?? '',
    run.head_commit_id ?? '',
    run.event_type,
    run.idempotency_key
  ];
  return candidates.some((item) => item.toLowerCase().includes(normalizedQuery));
};

export const deriveVisibleCodeReviewRuns = ({
  runs,
  repositories,
  runDetailsById,
  context,
  statusFilter,
  modeFilter,
  searchQuery
}: {
  runs: CodeReviewRunSummary[];
  repositories: CodeReviewRepositorySummary[];
  runDetailsById: Record<number, CodeReviewRunDetail>;
  context: PortalCodeReviewContext;
  statusFilter: PortalCodeReviewStatusFilter;
  modeFilter: PortalCodeReviewModeFilter;
  searchQuery: string;
}): PortalCodeReviewRunItem[] => {
  return runs
    .map<PortalCodeReviewRunItem>((run) => {
      const repository =
        repositories.find((item) => item.id === run.repository_integration_id) ?? null;
      const detail = runDetailsById[run.id];
      const mode = resolvePortalCodeReviewMode(detail);
      const pendingApprovalCount = getPendingApprovalCount(detail);
      const lastEventType =
        detail?.timeline_events[detail.timeline_events.length - 1]?.event_type ?? null;
      return {
        ...run,
        repository,
        repositoryName: repository?.full_name ?? '',
        repositoryDefaultBranch: repository?.default_branch ?? null,
        mode,
        hasPendingApproval: pendingApprovalCount > 0,
        pendingApprovalCount,
        findingsCount: detail?.findings.length ?? null,
        lastEventType
      };
    })
    .filter((run) => matchesCodeReviewRepositoryContext(run.repository, context))
    .filter((run) => (statusFilter === 'all' ? true : run.status === statusFilter))
    .filter((run) => (modeFilter === 'all' ? true : run.mode === modeFilter))
    .filter((run) => matchesRunSearch(run, searchQuery))
      .sort((left, right) => {
      if (left.hasPendingApproval !== right.hasPendingApproval) {
        return left.hasPendingApproval ? -1 : 1;
      }
      const leftTime = left.created_at ? Date.parse(left.created_at) : 0;
      const rightTime = right.created_at ? Date.parse(right.created_at) : 0;
      return rightTime - leftTime;
    });
};

export const deriveCodeReviewPrefetchRunIds = ({
  runs,
  repositories,
  runDetailsById,
  loadingDetailIds,
  context,
  statusFilter,
  searchQuery
}: {
  runs: CodeReviewRunSummary[];
  repositories: CodeReviewRepositorySummary[];
  runDetailsById: Record<number, CodeReviewRunDetail>;
  loadingDetailIds: Record<number, true>;
  context: PortalCodeReviewContext;
  statusFilter: PortalCodeReviewStatusFilter;
  searchQuery: string;
}) => {
  return deriveVisibleCodeReviewRuns({
    runs,
    repositories,
    runDetailsById,
    context,
    statusFilter,
    modeFilter: 'all',
    searchQuery
  })
    .map((run) => run.id)
    .filter((runId) => !(runId in runDetailsById) && !loadingDetailIds[runId]);
};

export const getCodeReviewEmptyStateMessage = ({
  hasSelectedRepository,
  hasLoadedInitialData,
  hasRepositories,
  visibleRunCount,
  hasFilters
}: {
  hasSelectedRepository: boolean;
  hasLoadedInitialData: boolean;
  hasRepositories: boolean;
  visibleRunCount: number;
  hasFilters: boolean;
}) => {
  if (!hasLoadedInitialData) {
    return '正在加载审查运行...';
  }
  if (!hasRepositories) {
    return '当前还没有可用的代码审查仓库';
  }
  if (!hasSelectedRepository) {
    return '请选择仓库后查看代码审查';
  }
  if (visibleRunCount > 0) {
    return '';
  }
  return hasFilters ? '没有匹配条件的审查运行' : '当前仓库还没有审查运行';
};

export const loadPortalCodeReviewSnapshot = async ({
  listRepositories,
  listRuns
}: LoadPortalCodeReviewSnapshotOptions) => {
  const [repositories, runs] = await Promise.all([
    listRepositories(),
    listRuns()
  ]);
  return { repositories, runs };
};

export const usePortalCodeReviewState = ({
  selectedRepo,
  selectedProvider,
  selectedGitlabBaseUrl,
  enabled = true
}: UsePortalCodeReviewStateOptions) => {
  const [repositories, setRepositories] = useState<CodeReviewRepositorySummary[]>([]);
  const [runs, setRuns] = useState<CodeReviewRunSummary[]>([]);
  const [runDetailsById, setRunDetailsById] = useState<Record<number, CodeReviewRunDetail>>(
    {}
  );
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] =
    useState<PortalCodeReviewStatusFilter>('all');
  const [modeFilter, setModeFilter] =
    useState<PortalCodeReviewModeFilter>('all');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [hasLoadedInitialData, setHasLoadedInitialData] = useState(false);
  const [isSyncingRepositories, setIsSyncingRepositories] = useState(false);
  const [loadingDetailIds, setLoadingDetailIds] = useState<Record<number, true>>({});
  const [selectedRunError, setSelectedRunError] = useState<string | null>(null);
  const [publishingRunIds, setPublishingRunIds] = useState<Record<number, true>>({});
  const [approvingFixRequestIds, setApprovingFixRequestIds] = useState<
    Record<number, true>
  >({});
  const [rejectingFixRequestIds, setRejectingFixRequestIds] = useState<
    Record<number, true>
  >({});
  const selectedRunIdRef = useRef<number | null>(null);
  const detailLoadGenerationRef = useRef(0);
  const inFlightDetailRequestsRef = useRef(new Map<number, Promise<void>>());
  const syncRequestKeyRef = useRef<string>('');

  const context = useMemo<PortalCodeReviewContext>(
    () => ({
      selectedRepo,
      selectedProvider,
      selectedGitlabBaseUrl
    }),
    [selectedGitlabBaseUrl, selectedProvider, selectedRepo]
  );

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      setIsRefreshing(true);
      detailLoadGenerationRef.current += 1;
      inFlightDetailRequestsRef.current.clear();
      const snapshot = await loadPortalCodeReviewSnapshot({
        listRepositories: listCodeReviewRepositories,
        listRuns: listCodeReviewRuns
      });
      setRepositories(snapshot.repositories);
      setRuns(snapshot.runs);
      setRunDetailsById({});
      setLoadingDetailIds({});
      setSelectedRunError(null);
    } catch (error) {
      console.error('Failed to load code review portal state', error);
      toast.error('加载代码审查数据失败，请稍后重试');
    } finally {
      setIsRefreshing(false);
      setHasLoadedInitialData(true);
    }
  }, [enabled]);

  const syncRepositories = useCallback(async () => {
    if (!enabled) return;
    const payload = buildCodeReviewSyncRequest(context);
    if (payload === null) return;
    try {
      setIsSyncingRepositories(true);
      await syncCodeReviewRepositories(payload);
      await refresh();
    } catch (error) {
      console.error('Failed to sync code review repositories', error);
      toast.error(getErrorMessage(error, '同步代码审查仓库失败，请稍后重试'));
    } finally {
      setIsSyncingRepositories(false);
    }
  }, [context, enabled, refresh]);

  useEffect(() => {
    if (!enabled) return;
    const payload = buildCodeReviewSyncRequest(context);
    if (payload === null) {
      void refresh();
      return;
    }
    const syncRequestKey = JSON.stringify(payload);
    if (syncRequestKeyRef.current === syncRequestKey) return;
    syncRequestKeyRef.current = syncRequestKey;
    void syncRepositories();
  }, [context, enabled, refresh, syncRepositories]);

  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  useEffect(() => {
    setSelectedRunError(null);
  }, [selectedRunId]);

  const visibleRuns = useMemo(
    () =>
      deriveVisibleCodeReviewRuns({
        runs,
        repositories,
        runDetailsById,
        context,
        statusFilter,
        modeFilter,
        searchQuery
    }),
    [context, modeFilter, repositories, runDetailsById, runs, searchQuery, statusFilter]
  );

  const prefetchRunIds = useMemo(
    () =>
      deriveCodeReviewPrefetchRunIds({
        runs,
        repositories,
        runDetailsById,
        loadingDetailIds,
        context,
        statusFilter,
        searchQuery
      }),
    [
      context,
      loadingDetailIds,
      repositories,
      runDetailsById,
      runs,
      searchQuery,
      statusFilter
    ]
  );

  useEffect(() => {
    if (visibleRuns.length === 0) {
      setSelectedRunId(null);
      return;
    }
    if (selectedRunId !== null && visibleRuns.some((run) => run.id === selectedRunId)) {
      return;
    }
    setSelectedRunId(visibleRuns[0]?.id ?? null);
  }, [selectedRunId, visibleRuns]);

  const loadRunDetail = useCallback(
    async (runId: number, options?: { silent?: boolean }) => {
      const existingRequest = inFlightDetailRequestsRef.current.get(runId);
      if (existingRequest) {
        await existingRequest;
        return;
      }

      const generation = detailLoadGenerationRef.current;
      const request = (async () => {
        setLoadingDetailIds((current) => ({ ...current, [runId]: true }));
        try {
          const detail = await getCodeReviewRun(runId);
          if (detailLoadGenerationRef.current !== generation) {
            return;
          }
          setRunDetailsById((current) => ({ ...current, [runId]: detail }));
          if (selectedRunIdRef.current === runId) {
            setSelectedRunError(null);
          }
        } catch (error) {
          console.error('Failed to load code review run detail', error);
          if (detailLoadGenerationRef.current !== generation) {
            return;
          }
          if (!options?.silent && selectedRunIdRef.current === runId) {
            setSelectedRunError('加载审查详情失败，请稍后重试');
            toast.error('加载审查详情失败，请稍后重试');
          }
        } finally {
          if (inFlightDetailRequestsRef.current.get(runId) === request) {
            inFlightDetailRequestsRef.current.delete(runId);
            setLoadingDetailIds((current) => {
              const next = { ...current };
              delete next[runId];
              return next;
            });
          }
        }
      })();

      inFlightDetailRequestsRef.current.set(runId, request);
      await request;
    },
    []
  );

  useEffect(() => {
    if (!enabled) return;
    if (prefetchRunIds.length === 0) return;

    void Promise.all(
      prefetchRunIds.map(async (runId) => {
        await loadRunDetail(runId, { silent: true });
      })
    );
  }, [enabled, loadRunDetail, prefetchRunIds]);

  useEffect(() => {
    if (!enabled || selectedRunId === null) return;
    if (runDetailsById[selectedRunId] || loadingDetailIds[selectedRunId]) return;
    void loadRunDetail(selectedRunId);
  }, [enabled, loadRunDetail, loadingDetailIds, runDetailsById, selectedRunId]);

  const publishRun = useCallback(
    async (runId: number) => {
      setPublishingRunIds((current) => ({ ...current, [runId]: true }));
      try {
        await publishCodeReviewRun(runId);
        toast.success('审查结果已发布');
        await loadRunDetail(runId, { silent: true });
      } catch (error) {
        console.error('Failed to publish code review run', error);
        toast.error(getErrorMessage(error, '发布审查结果失败，请稍后重试'));
      } finally {
        setPublishingRunIds((current) => {
          const next = { ...current };
          delete next[runId];
          return next;
        });
      }
    },
    [loadRunDetail]
  );

  const approveFixRequest = useCallback(
    async (fixRequestId: number, runId: number) => {
      setApprovingFixRequestIds((current) => ({ ...current, [fixRequestId]: true }));
      try {
        await approveCodeReviewFixRequest(fixRequestId);
        toast.success('修复请求已批准');
        await loadRunDetail(runId, { silent: true });
      } catch (error) {
        console.error('Failed to approve code review fix request', error);
        toast.error(getErrorMessage(error, '批准修复请求失败，请稍后重试'));
      } finally {
        setApprovingFixRequestIds((current) => {
          const next = { ...current };
          delete next[fixRequestId];
          return next;
        });
      }
    },
    [loadRunDetail]
  );

  const rejectFixRequest = useCallback(
    async (fixRequestId: number, runId: number) => {
      setRejectingFixRequestIds((current) => ({ ...current, [fixRequestId]: true }));
      try {
        await rejectCodeReviewFixRequest(fixRequestId);
        toast.success('修复请求已拒绝');
        await loadRunDetail(runId, { silent: true });
      } catch (error) {
        console.error('Failed to reject code review fix request', error);
        toast.error(getErrorMessage(error, '拒绝修复请求失败，请稍后重试'));
      } finally {
        setRejectingFixRequestIds((current) => {
          const next = { ...current };
          delete next[fixRequestId];
          return next;
        });
      }
    },
    [loadRunDetail]
  );

  const selectedRun = selectedRunId === null ? null : runDetailsById[selectedRunId] ?? null;
  const hasFilters =
    statusFilter !== 'all' || modeFilter !== 'all' || searchQuery.trim().length > 0;
  const emptyStateMessage = getCodeReviewEmptyStateMessage({
    hasSelectedRepository: selectedRepo.trim().length > 0,
    hasLoadedInitialData:
      hasLoadedInitialData &&
      !(modeFilter !== 'all' && prefetchRunIds.length > 0 && visibleRuns.length === 0),
    hasRepositories: repositories.length > 0,
    visibleRunCount: visibleRuns.length,
    hasFilters
  });

  return {
    repositories,
    runs,
    visibleRuns,
    selectedRunId,
    setSelectedRunId,
    selectedRun,
    selectedRunError,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    modeFilter,
    setModeFilter,
    isRefreshing,
    hasLoadedInitialData,
    isSyncingRepositories,
    isSelectedRunLoading:
      selectedRunId !== null ? Boolean(loadingDetailIds[selectedRunId]) : false,
    pendingApprovalCount: visibleRuns.reduce(
      (total, run) => total + run.pendingApprovalCount,
      0
    ),
    hasPendingApprovalRuns: visibleRuns.some((run) => run.hasPendingApproval),
    emptyStateMessage,
    refresh,
    syncRepositories,
    loadRunDetail,
    publishRun,
    approveFixRequest,
    rejectFixRequest,
    publishingRunIds,
    approvingFixRequestIds,
    rejectingFixRequestIds
  };
};
