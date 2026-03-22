import { useCallback, useEffect, useMemo, useState } from 'react';
import { type Thread } from '@langchain/langgraph-sdk';
import { toast } from 'sonner';
import { mapThreadsToTaskItems, type TaskItem } from '@/lib/tasks';

type UsePortalTaskStateOptions = {
  threads: Thread[];
  threadsLoading: boolean;
  getThreads: () => Promise<unknown>;
  deleteThread: (threadId: string) => Promise<void>;
  cancelThreadRun: (threadId: string) => Promise<boolean>;
};

export const usePortalTaskState = ({
  threads,
  threadsLoading,
  getThreads,
  deleteThread,
  cancelThreadRun
}: UsePortalTaskStateOptions) => {
  const [taskQuery, setTaskQuery] = useState('');
  const [taskSearchOpen, setTaskSearchOpen] = useState(false);
  const [pendingDeleteTask, setPendingDeleteTask] = useState<TaskItem | null>(
    null
  );
  const [isDeletingTask, setIsDeletingTask] = useState(false);
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null);
  const [hasLoadedTasks, setHasLoadedTasks] = useState(false);

  const tasks = useMemo(() => mapThreadsToTaskItems(threads), [threads]);
  const visibleTasks = useMemo(() => {
    const query = taskQuery.trim().toLowerCase();
    if (!query) return tasks;
    return tasks.filter(
      (item) =>
        item.title.toLowerCase().includes(query) ||
        item.repo.toLowerCase().includes(query)
    );
  }, [taskQuery, tasks]);
  const isTasksLoading = useMemo(
    () =>
      (!hasLoadedTasks && threads.length === 0) ||
      (threadsLoading && threads.length === 0),
    [hasLoadedTasks, threads.length, threadsLoading]
  );

  useEffect(() => {
    let isCancelled = false;
    getThreads()
      .catch((error) => {
        console.error('Failed to load tasks from threads', error);
      })
      .finally(() => {
        if (!isCancelled) setHasLoadedTasks(true);
      });
    return () => {
      isCancelled = true;
    };
  }, [getThreads]);

  const handleDeleteTask = useCallback(async () => {
    if (!pendingDeleteTask || isDeletingTask) return;
    try {
      setIsDeletingTask(true);
      await deleteThread(pendingDeleteTask.id);
      toast.success('任务已删除');
      setTaskSearchOpen(false);
      setPendingDeleteTask(null);
    } catch (error) {
      console.error('Failed to delete task thread', error);
      toast.error('删除任务失败，请稍后重试');
    } finally {
      setIsDeletingTask(false);
    }
  }, [deleteThread, isDeletingTask, pendingDeleteTask]);

  const handleCancelTaskRun = useCallback(
    async (item: TaskItem) => {
      if (cancellingTaskId) return;
      try {
        setCancellingTaskId(item.id);
        const cancelled = await cancelThreadRun(item.id);
        if (!cancelled) {
          toast.info('当前没有可取消的执行任务');
          return;
        }
        toast.success('已取消任务执行');
      } catch (error) {
        console.error('Failed to cancel task run', error);
        toast.error('取消任务执行失败，请稍后重试');
      } finally {
        setCancellingTaskId(null);
      }
    },
    [cancelThreadRun, cancellingTaskId]
  );

  return {
    tasks,
    taskQuery,
    setTaskQuery,
    taskSearchOpen,
    setTaskSearchOpen,
    pendingDeleteTask,
    setPendingDeleteTask,
    isDeletingTask,
    cancellingTaskId,
    visibleTasks,
    isTasksLoading,
    handleDeleteTask,
    handleCancelTaskRun
  };
};
