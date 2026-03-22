import React from 'react';
import { Spinner } from '@/components/ui/spinner';
import { TabsContent } from '@/components/ui/tabs';
import { TaskListItem } from '@/components/task-list-item';
import {
  PortalCodeReviewFilters,
  type PortalCodeReviewListProps,
  PortalCodeReviewList
} from '@/business/portal/portal-code-review-list';
import { PortalCodeReviewDetail } from '@/business/portal/portal-code-review-detail';
import { type CodeReviewRunDetail } from '@/business/portal/code-review-types';
import { statusLabel, type TaskItem } from '@/lib/tasks';

type PortalTaskContentProps = {
  visibleTasks: TaskItem[];
  isTasksLoading: boolean;
  onTaskClick: (item: TaskItem) => void;
  onTaskDelete: (item: TaskItem) => void;
  onTaskCancelRun: (item: TaskItem) => void;
  cancellingTaskId?: string | null;
  codeReviewListProps: PortalCodeReviewListProps;
  selectedCodeReviewRunId: number | null;
  onBackFromCodeReviewDetail: () => void;
  selectedCodeReviewRun: CodeReviewRunDetail | null;
  selectedCodeReviewRunError: string | null;
  isSelectedCodeReviewRunLoading: boolean;
  onRetryCodeReviewRun: () => void | Promise<void>;
  onPublishCodeReviewRun: (runId: number) => void | Promise<void>;
  onContinueCodeReviewFix: (run: CodeReviewRunDetail) => void | Promise<void>;
  onApproveCodeReviewFixRequest: (
    fixRequestId: number,
    runId: number
  ) => void | Promise<void>;
  onRejectCodeReviewFixRequest: (
    fixRequestId: number,
    runId: number
  ) => void | Promise<void>;
  canContinueCodeReviewFix: boolean;
  continueCodeReviewFixHint?: string | null;
  publishingCodeReviewRunIds?: Record<number, true>;
  approvingCodeReviewFixRequestIds?: Record<number, true>;
  rejectingCodeReviewFixRequestIds?: Record<number, true>;
};

export function PortalTaskContent({
  visibleTasks,
  isTasksLoading,
  onTaskClick,
  onTaskDelete,
  onTaskCancelRun,
  cancellingTaskId,
  codeReviewListProps,
  selectedCodeReviewRunId,
  onBackFromCodeReviewDetail,
  selectedCodeReviewRun,
  selectedCodeReviewRunError,
  isSelectedCodeReviewRunLoading,
  onRetryCodeReviewRun,
  onPublishCodeReviewRun,
  onContinueCodeReviewFix,
  onApproveCodeReviewFixRequest,
  onRejectCodeReviewFixRequest,
  canContinueCodeReviewFix,
  continueCodeReviewFixHint,
  publishingCodeReviewRunIds,
  approvingCodeReviewFixRequestIds,
  rejectingCodeReviewFixRequestIds
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
        <div className="min-h-95 pt-4">
          <div className="space-y-4">
            <PortalCodeReviewFilters {...codeReviewListProps} />
            {selectedCodeReviewRunId === null ? (
              <PortalCodeReviewList {...codeReviewListProps} />
            ) : (
              <PortalCodeReviewDetail
                selectedRunId={selectedCodeReviewRunId}
                run={selectedCodeReviewRun}
                isLoading={isSelectedCodeReviewRunLoading}
                errorMessage={selectedCodeReviewRunError}
                onRetry={onRetryCodeReviewRun}
                onBack={onBackFromCodeReviewDetail}
                onPublishRun={onPublishCodeReviewRun}
                onContinueFix={onContinueCodeReviewFix}
                onApproveFixRequest={onApproveCodeReviewFixRequest}
                onRejectFixRequest={onRejectCodeReviewFixRequest}
                canContinueFix={canContinueCodeReviewFix}
                continueFixHint={continueCodeReviewFixHint}
                publishingRunIds={publishingCodeReviewRunIds}
                approvingFixRequestIds={approvingCodeReviewFixRequestIds}
                rejectingFixRequestIds={rejectingCodeReviewFixRequestIds}
              />
            )}
          </div>
        </div>
      </TabsContent>
    </>
  );
}
