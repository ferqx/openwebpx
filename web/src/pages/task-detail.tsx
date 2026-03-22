import { TaskDetailHeader } from '@/business/task-detail/task-detail-header';
import {
  formatThreadCreatedAt,
  getErrorMessage,
  getErrorStatusCode,
  getThreadNameFromMetadata,
  getThreadReviewCommentPublishStatus
} from '@/business/task-detail/task-detail-utils';
import { ThreadChatPanel } from '@/business/thread-chat/thread-chat-panel';
import { Button } from '@/components/ui/button';
import { useTaskDetailGitDiff } from '@/hooks/use-task-detail-git-diff';
import { useTaskDetailMessageHydration } from '@/hooks/use-task-detail-message-hydration';
import { useThreadChat } from '@/hooks/use-thread-chat';
import {
  commitSandboxThreadGitChanges,
  type SandboxThreadGitCommitResult
} from '@/lib/sandbox';
import { mapThreadToTaskItem } from '@/lib/tasks';
import {
  buildBackToPortalState,
  deriveInitialAutoRunState,
  stripConsumedTaskRouteState,
  type TaskRouteState
} from '@/pages/task-detail-route-state';
import { useStreamContext } from '@/provider/stream';
import { useThreads } from '@/provider/thread';
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

export function TaskDetailPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams();
  const { threads, getThreads, threadsLoading, cancelThreadRun } = useThreads();
  const streamContext = useStreamContext();
  const {
    messages,
    isLoading,
    isThreadLoading,
    error,
    submit,
    stop,
    joinStream
  } =
    streamContext;
  const { hydratedMessages, isInitialMessageHydrating } =
    useTaskDetailMessageHydration({
      threadId: id,
      messages,
      isThreadLoading
    });
  const deferredMessages = useDeferredValue(hydratedMessages);
  const deferredIsLoading = useDeferredValue(isLoading);
  const chatInputMessages = useMemo(() => {
    // Hydration完成后的短窗口内，deferred 可能还没追上真实消息，
    // 会出现“先显示顶部环境日志，再补历史消息”的抖动。
    // 该场景优先使用即时消息，保证首次落地渲染同步。
    if (
      !isInitialMessageHydrating &&
      hydratedMessages.length > 0 &&
      deferredMessages.length === 0
    ) {
      return hydratedMessages;
    }
    return deferredMessages;
  }, [deferredMessages, hydratedMessages, isInitialMessageHydrating]);

  // 路由态只用于首轮进入时的兜底信息与自动运行参数。
  const routeState = location.state as TaskRouteState | null;
  const routeTask = routeState?.task;
  const [initialAutoRun] = useState(() => deriveInitialAutoRunState(routeState));
  const initialPrompt = initialAutoRun.prompt;
  const requestedThreadIdsRef = useRef<Set<string>>(new Set());
  const autoSubmittedThreadIdsRef = useRef<Set<string>>(new Set());
  const [threadLoadErrorById, setThreadLoadErrorById] = useState<
    Record<string, unknown>
  >({});
  const [threadLoadCheckedById, setThreadLoadCheckedById] = useState<
    Record<string, boolean>
  >({});
  const previousChatStatusRef = useRef<string | null>(null);
  const autoRunStorageKey = useMemo(
    () => (id ? `task:auto-run:${id}` : ''),
    [id]
  );

  // 自动运行参数消费后，清理 shouldAutoRun，避免刷新后重复触发。
  useEffect(() => {
    if (!routeState?.shouldAutoRun) return;
    const nextState = stripConsumedTaskRouteState(routeState);

    navigate(location.pathname, {
      replace: true,
      state: nextState
    });
  }, [
    location.pathname,
    navigate,
    routeState?.shouldAutoRun,
    routeState
  ]);

  // 线程列表拉取只做“是否存在当前线程”的检查，不直接参与消息渲染。
  useEffect(() => {
    if (!id) return;
    if (threads.some((thread) => thread.thread_id === id)) return;
    if (requestedThreadIdsRef.current.has(id)) return;
    requestedThreadIdsRef.current.add(id);
    getThreads()
      .then(() => {
        setThreadLoadCheckedById((prev) => ({ ...prev, [id]: true }));
      })
      .catch((threadError) => {
        setThreadLoadCheckedById((prev) => ({ ...prev, [id]: true }));
        setThreadLoadErrorById((prev) => ({ ...prev, [id]: threadError }));
        console.error('Failed to load threads for task detail', threadError);
      });
  }, [getThreads, id, threads]);

  // UI 渲染只基于展示消息（deferred）与 stream 状态。
  const linkedThread = useMemo(
    () => threads.find((thread) => thread.thread_id === id),
    [id, threads]
  );
  const task = useMemo(() => {
    if (routeTask) return routeTask;
    if (linkedThread) return mapThreadToTaskItem(linkedThread);
    return undefined;
  }, [linkedThread, routeTask]);
  const threadName = useMemo(
    () =>
      getThreadNameFromMetadata(linkedThread) ?? task?.title ?? '未命名线程',
    [linkedThread, task?.title]
  );
  const threadCreatedAt = useMemo(
    () =>
      formatThreadCreatedAt(linkedThread?.created_at) ??
      formatThreadCreatedAt(task?.createdAt) ??
      task?.dateLabel ??
      '未知',
    [linkedThread?.created_at, task?.createdAt, task?.dateLabel]
  );
  const reviewCommentStatus = useMemo(
    () => getThreadReviewCommentPublishStatus(linkedThread),
    [linkedThread]
  );
  const showTaskTitle = Boolean(task && task.title !== threadName);
  const threadLoadError =
    id && !linkedThread ? threadLoadErrorById[id] : undefined;
  const pageError = threadLoadError;
  const pageErrorStatus = getErrorStatusCode(pageError);
  const isNotFound = pageErrorStatus === 404;
  const hasThreadCheckFinished =
    Boolean(linkedThread) || (id ? Boolean(threadLoadCheckedById[id]) : true);
  const {
    input,
    setInput,
    chatStatus,
    chatMessages,
    immediateResponding,
    hasTurnFailureMessages,
    isEnvironmentBootstrapHydrated,
    tokenUsageSummary,
    isThinking,
    handleSubmit,
    isEnvironmentResetting,
    resetEnvironmentInitialization
  } = useThreadChat({
    messages: chatInputMessages,
    isLoading: deferredIsLoading,
    error,
    submit,
    joinStream,
    threadId: id,
    initialOptimisticUserText: initialAutoRun.shouldAutoRun
      ? initialPrompt
      : undefined,
    enableEnvironmentInitialization: !isInitialMessageHydrating,
    enableSyntheticPendingToolMessage: true
  });
  const visibleChatMessages = chatMessages;
  const canRefreshGitDiff =
    hasThreadCheckFinished &&
    isEnvironmentBootstrapHydrated &&
    chatStatus !== 'submitted' &&
    chatStatus !== 'streaming';
  const { gitDiffState, refreshGitDiff } = useTaskDetailGitDiff({
    threadId: id,
    enabled: hasThreadCheckFinished,
    blockRefresh: !canRefreshGitDiff,
    isNotFound,
    pageError
  });
  const handleSubmitRef = useRef(handleSubmit);
  const stopRef = useRef(stop);
  const cancellingRunRef = useRef(false);

  useEffect(() => {
    const previousChatStatus = previousChatStatusRef.current;
    if (!id || !previousChatStatus) return;
    const previousWasRunning =
      previousChatStatus === 'submitted' || previousChatStatus === 'streaming';
    const nowCompleted = chatStatus === 'ready' || chatStatus === 'error';
    if (previousWasRunning && nowCompleted) {
      void refreshGitDiff();
    }
  }, [chatStatus, id, refreshGitDiff]);

  useEffect(() => {
    previousChatStatusRef.current = chatStatus;
  }, [chatStatus]);

  useEffect(() => {
    handleSubmitRef.current = handleSubmit;
  }, [handleSubmit]);

  useEffect(() => {
    stopRef.current = stop;
  }, [stop]);

  const stableHandleSubmit = useCallback(
    (message: Parameters<typeof handleSubmit>[0]) =>
      handleSubmitRef.current(message),
    []
  );

  const stableStopGenerating = useCallback(() => {
    stopRef.current?.();
    if (!id || cancellingRunRef.current) return;

    cancellingRunRef.current = true;
    void cancelThreadRun(id)
      .then((cancelled) => {
        if (cancelled) {
          toast.success('已取消任务执行');
          return;
        }
        toast.info('当前没有可取消的执行任务');
      })
      .catch((cancelError) => {
        console.error('Failed to cancel task run from task detail', cancelError);
        toast.error('取消任务执行失败，请稍后重试');
      })
      .finally(() => {
        cancellingRunRef.current = false;
      });
  }, [cancelThreadRun, id]);

  const handleResetEnvironmentInitialization = useCallback(async () => {
    try {
      await resetEnvironmentInitialization();
      toast.success('环境初始化已重置');
    } catch (resetError) {
      console.error('Failed to reset environment initialization', resetError);
      toast.error(getErrorMessage(resetError));
    }
  }, [resetEnvironmentInitialization]);

  const handleCommitChanges = useCallback(
    async (payload: {
      message?: string;
      generateMessage: boolean;
    }): Promise<SandboxThreadGitCommitResult> => {
      const threadId = id?.trim();
      if (!threadId) {
        throw new Error('threadId is required');
      }
      const result = await commitSandboxThreadGitChanges(threadId, {
        message: payload.message,
        generate_message: payload.generateMessage
      });
      return result;
    },
    [id]
  );

  // 初始 prompt 仅在该线程首次进入且无历史消息时自动提交一次。
  useEffect(() => {
    if (!id || !initialPrompt) return;
    if (typeof window !== 'undefined' && autoRunStorageKey) {
      const hasAutoRun = window.sessionStorage.getItem(autoRunStorageKey);
      if (hasAutoRun === '1') return;
    }
    if (autoSubmittedThreadIdsRef.current.has(id)) return;
    if (isThreadLoading || isLoading) return;

    autoSubmittedThreadIdsRef.current.add(id);
    if (typeof window !== 'undefined' && autoRunStorageKey) {
      window.sessionStorage.setItem(autoRunStorageKey, '1');
    }
    stableHandleSubmit({ text: initialPrompt, files: [] }).catch((submitError) => {
      if (typeof window !== 'undefined' && autoRunStorageKey) {
        window.sessionStorage.removeItem(autoRunStorageKey);
      }
      autoSubmittedThreadIdsRef.current.delete(id);
      console.error('Failed to auto submit initial task prompt', submitError);
    });
  }, [
    autoRunStorageKey,
    id,
    initialPrompt,
    isLoading,
    isThreadLoading,
    stableHandleSubmit
  ]);

  // 返回时尽量保持门户页 tab 上下文。
  const handleBackToPortal = () => {
    const nextState = buildBackToPortalState(routeState);
    if (nextState) {
      navigate('/', { state: nextState });
      return;
    }
    navigate('/');
  };

  // 页面状态优先级：
  // 1) 初始 loading -> 2) 线程加载错误/404 -> 3) 正常会话区（由 ThreadChatPanel 决定空态/消息）。
  const isInitialLoading =
    !pageError &&
    (!hasThreadCheckFinished ||
      isThreadLoading ||
      threadsLoading ||
      isInitialMessageHydrating ||
      !gitDiffState.hasLoaded);
  const showPageLoading =
    (isInitialLoading || !isEnvironmentBootstrapHydrated) &&
    visibleChatMessages.length === 0 &&
    !isLoading;
  if (showPageLoading) {
    return (
      <main className="flex h-full items-center justify-center bg-background p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="inline-flex size-4 animate-spin rounded-full border-2 border-muted-foreground/20 border-t-muted-foreground" />
          <span>正在加载会话...</span>
        </div>
      </main>
    );
  }

  if (pageError && !isNotFound) {
    return (
      <main className="flex h-full items-center justify-center bg-background p-6">
        <div className="max-w-xl space-y-4 text-center">
          <p className="text-lg font-medium">会话加载失败</p>
          <p className="wrap-break-word text-sm text-muted-foreground">
            {getErrorMessage(pageError)}
          </p>
          <Button type="button" variant="outline" onClick={handleBackToPortal}>
            返回门户
          </Button>
        </div>
      </main>
    );
  }

  if ((isNotFound || !task) && !isInitialLoading) {
    return (
      <main className="flex h-full items-center justify-center bg-background p-6">
        <div className="space-y-4 text-center">
          <p className="text-lg font-medium">线程不存在或已被删除</p>
          <Button type="button" variant="outline" onClick={handleBackToPortal}>
            返回门户
          </Button>
        </div>
      </main>
    );
  }

  return (
    <main className="flex h-full min-h-0 flex-col bg-background">
      <TaskDetailHeader
        branch={task?.branch}
        gitDiffError={gitDiffState.error}
        isGitDiffLoading={gitDiffState.loading}
        repo={task?.repo}
        reviewCommentStatus={reviewCommentStatus}
        showTaskTitle={showTaskTitle}
        stagedChanges={gitDiffState.staged}
        threadId={id}
        taskTitle={task?.title}
        threadCreatedAt={threadCreatedAt}
        threadName={threadName}
        unstagedChanges={gitDiffState.unstaged}
        onCommitChanges={handleCommitChanges}
        onBackToPortal={handleBackToPortal}
        onRefreshGitDiff={() => refreshGitDiff()}
      />

      <div className="mx-auto flex min-h-0 w-full flex-1 flex-col">
        <ThreadChatPanel
          threadId={id}
          chatMessages={visibleChatMessages}
          isLoading={isLoading}
          isInitializing={isInitialLoading && visibleChatMessages.length === 0}
          isThinking={isThinking}
          chatStatus={chatStatus}
          immediateResponding={immediateResponding}
          hasTurnFailureMessages={hasTurnFailureMessages}
          tokenUsageSummary={tokenUsageSummary}
          error={error}
          input={input}
          onInputChange={setInput}
          onSubmit={stableHandleSubmit}
          isEnvironmentResetting={isEnvironmentResetting}
          onResetEnvironmentInitialization={handleResetEnvironmentInitialization}
          onStopGenerating={stableStopGenerating}
          emptyTitle="还没有会话内容"
          emptyDescription="请提出你的问题"
          placeholder="请求更改或提出问题"
        />
      </div>
    </main>
  );
}
