import { type Metadata, type Run, type Thread } from '@langchain/langgraph-sdk';
import {
  createContext,
  useContext,
  type ReactNode,
  useCallback,
  useState,
  type Dispatch,
  type SetStateAction,
  useMemo
} from 'react';
import { client } from '../lib/langgraph-sdk';
import { useLocation, useParams } from 'react-router-dom';
import { resolveAgentConfigByPath } from '@/lib/agent-config';
import { cancelSandboxThreadRuns } from '@/lib/sandbox';

interface ThreadContextType {
  getThreads: (metadata?: Metadata) => Promise<Thread[]>;
  createThread: (name: string) => Promise<Thread>;
  deleteThread: (threadId: string) => Promise<void>;
  cancelThreadRun: (threadId: string) => Promise<boolean>;
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
  threadsLoading: boolean;
  currentThread?: Thread;
  setThreadsLoading: Dispatch<SetStateAction<boolean>>;
}

const ThreadContext = createContext<ThreadContextType | undefined>(undefined);

const isHttpStatusError = (error: unknown, statuses: number[]) => {
  if (!error || typeof error !== 'object') return false;
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' && statuses.includes(status);
};

export function ThreadProvider({ children }: { children: ReactNode }) {
  const params = useParams();
  const location = useLocation();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const activeGraphId = useMemo(
    () => resolveAgentConfigByPath(location.pathname).graphId,
    [location.pathname]
  );

  const getThreads = useCallback(
    async (metadata?: Metadata): Promise<Thread[]> => {
      setThreadsLoading(true);
      const mergedMetadata: Record<string, unknown> =
        metadata && typeof metadata === 'object' ? { ...metadata } : {};
      if (!mergedMetadata.graph_id) {
        mergedMetadata.graph_id = activeGraphId;
      }
      try {
        const threads = await client.threads.search({
          metadata: mergedMetadata as Metadata,
          offset: 0,
          limit: 100
        });
        setThreads(threads);
        return threads;
      } finally {
        setThreadsLoading(false);
      }
    },
    [activeGraphId]
  );

  const createThread = useCallback(async (name: string): Promise<Thread> => {
    const thread = await client.threads.create({
      metadata: { name, graph_id: activeGraphId }
    });
    setThreads((prev) => [thread, ...prev]);
    return thread;
  }, [activeGraphId]);

  const cancelThreadRun = useCallback(
    async (threadId: string): Promise<boolean> => {
      const previousThread = threads.find(
        (thread) => thread.thread_id === threadId
      );
      const wasBusyBeforeCancel = previousThread?.status === 'busy';

      try {
        const cancelResult = await cancelSandboxThreadRuns(threadId, 'interrupt');
        if (typeof window !== 'undefined') {
          window.sessionStorage.removeItem(`lg:stream:${threadId}`);
        }
        await getThreads();
        return (
          cancelResult.cancelled_run_count > 0 ||
          cancelResult.bootstrap_task_cancelled ||
          cancelResult.cancel_signal_failures.length > 0 ||
          wasBusyBeforeCancel
        );
      } catch (threadCancelError) {
        // Backward compatibility for older backends that don't expose /sandbox/threads/{thread_id}/cancel.
        if (!isHttpStatusError(threadCancelError, [404, 405])) {
          throw threadCancelError;
        }
      }

      const runs = await client.runs.list(threadId, { limit: 20 });
      const activeRun = runs
        .filter((run: Run) => run.status === 'pending' || run.status === 'running')
        .sort((left, right) => {
          const leftUpdatedAt = new Date(left.updated_at).getTime();
          const rightUpdatedAt = new Date(right.updated_at).getTime();
          return rightUpdatedAt - leftUpdatedAt;
        })[0];

      if (!activeRun) return false;

      await client.runs.cancel(threadId, activeRun.run_id, true, 'interrupt');
      if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem(`lg:stream:${threadId}`);
      }
      await getThreads();
      return true;
    },
    [getThreads, threads]
  );

  const deleteThread = useCallback(async (threadId: string) => {
    await client.threads.delete(threadId);
    setThreads((prev) =>
      prev.filter((thread) => thread.thread_id !== threadId)
    );
  }, []);

  const currentThread = useMemo(() => {
    return threads.find((thread) => thread.thread_id === params.id);
  }, [threads, params.id]);

  const value = {
    getThreads,
    createThread,
    deleteThread,
    cancelThreadRun,
    setThreads,
    setThreadsLoading,
    threads,
    currentThread,
    threadsLoading
  };

  return (
    <ThreadContext.Provider value={value}>{children}</ThreadContext.Provider>
  );
}

export function useThreads() {
  const context = useContext(ThreadContext);
  if (context === undefined) {
    throw new Error('useThreads must be used within a ThreadProvider');
  }
  return context;
}
