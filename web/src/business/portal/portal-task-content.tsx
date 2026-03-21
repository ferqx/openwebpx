import { Bug } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { TabsContent } from '@/components/ui/tabs';
import { TaskListItem } from '@/components/task-list-item';
import { statusLabel, type TaskItem } from '@/lib/tasks';

type PortalTaskContentProps = {
  visibleTasks: TaskItem[];
  isTasksLoading: boolean;
  autoCodeReview: boolean;
  onTaskClick: (item: TaskItem) => void;
  onTaskDelete: (item: TaskItem) => void;
  onTaskCancelRun: (item: TaskItem) => void;
  cancellingTaskId?: string | null;
  onOpenReviewSettings: () => void;
};

export function PortalTaskContent({
  visibleTasks,
  isTasksLoading,
  autoCodeReview,
  onTaskClick,
  onTaskDelete,
  onTaskCancelRun,
  cancellingTaskId,
  onOpenReviewSettings
}: PortalTaskContentProps) {
  return (
    <>
      <TabsContent value="tasks">
        <div className="min-h-95 pt-4">
          {isTasksLoading ? (
            <div className="flex min-h-80 items-center justify-center gap-2 text-muted-foreground">
              <Spinner className="size-5" />
              <span>正在加载任务...</span>
            </div>
          ) : visibleTasks.length === 0 ? (
            <div className="flex min-h-80 items-center justify-center text-2xl text-muted-foreground">
              没有任务
            </div>
          ) : (
            <div className="space-y-3">
              <p className="px-1 text-sm text-muted-foreground">今天</p>
              <div className="divide-y bg-card">
                {visibleTasks.map((item) => (
                  <div
                    className="cursor-pointer transition-colors hover:bg-muted/80"
                    key={item.id}
                    onClick={() => onTaskClick(item)}
                  >
                    <TaskListItem
                      title={item.title}
                      subtitle={`${item.updatedAt} · ${item.repo} · ${item.branch}`}
                      status={item.status}
                      statusText={statusLabel[item.status]}
                      onCancel={
                        item.status === 'running' || item.status === 'starting'
                          ? () => onTaskCancelRun(item)
                          : undefined
                      }
                      cancelDisabled={cancellingTaskId === item.id}
                      onDelete={() => onTaskDelete(item)}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </TabsContent>

      <TabsContent value="review">
        <div className="flex min-h-95 items-center justify-center">
          <div className="flex max-w-2xl flex-col items-center gap-5 text-center">
            <div className="bg-card ring-foreground/10 flex size-20 items-center justify-center rounded-3xl ring-1 shadow-xs">
              <Bug className="size-10" />
            </div>
            <h2 className="text-2xl font-semibold">
              {autoCodeReview ? '代码审查已启用' : '代码审查未启用'}
            </h2>
            <p className="text-base text-muted-foreground">
              {autoCodeReview
                ? '将自动审核你推送至关联存储库的 PR。'
                : '启用后，将在你推送 PR 时自动执行审查。'}
            </p>
            <Button
              className="min-w-72 rounded-full"
              size="lg"
              type="button"
              onClick={onOpenReviewSettings}
            >
              {autoCodeReview ? '管理代码审查' : '启用代码审查'}
            </Button>
          </div>
        </div>
      </TabsContent>

    </>
  );
}
