import { TaskDetailDiffSheet } from '@/business/task-detail/task-detail-diff-sheet';
import {
  TaskDetailReviewStatus,
  type ReviewCommentPublishStatus
} from '@/business/task-detail/task-detail-review-status';
import {
  type SandboxThreadGitChangesResult,
  type SandboxThreadGitCommitResult
} from '@/lib/sandbox';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ArrowLeft } from 'lucide-react';

type TaskDetailHeaderProps = {
  threadName: string;
  showTaskTitle: boolean;
  taskTitle?: string;
  threadCreatedAt: string;
  repo?: string;
  branch?: string;
  reviewCommentStatus?: ReviewCommentPublishStatus;
  threadId?: string;
  stagedChanges: SandboxThreadGitChangesResult | null;
  unstagedChanges: SandboxThreadGitChangesResult | null;
  isGitDiffLoading: boolean;
  gitDiffError?: string;
  onRefreshGitDiff: () => void | Promise<void>;
  onCommitChanges: (payload: {
    message?: string;
    generateMessage: boolean;
  }) => Promise<SandboxThreadGitCommitResult>;
  onBackToPortal: () => void;
};

export function TaskDetailHeader({
  threadName,
  showTaskTitle,
  taskTitle,
  threadCreatedAt,
  repo,
  branch,
  reviewCommentStatus,
  threadId,
  stagedChanges,
  unstagedChanges,
  isGitDiffLoading,
  gitDiffError,
  onRefreshGitDiff,
  onCommitChanges,
  onBackToPortal
}: TaskDetailHeaderProps) {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex w-full flex-col gap-3 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              aria-label="返回任务列表"
              size="icon-lg"
              type="button"
              variant="ghost"
              onClick={onBackToPortal}
            >
              <ArrowLeft className="size-5" />
            </Button>
            <Separator orientation="vertical" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{threadName}</p>
              <p className="truncate text-sm text-muted-foreground">
                {showTaskTitle ? `任务：${taskTitle || '--'} · ` : ''}
                创建时间：{threadCreatedAt} · {repo || '--'} · {branch || '--'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1 md:gap-2">
            <TaskDetailDiffSheet
              threadId={threadId}
              branch={branch}
              stagedChanges={stagedChanges}
              unstagedChanges={unstagedChanges}
              isLoading={isGitDiffLoading}
              error={gitDiffError}
              onRefresh={onRefreshGitDiff}
              onCommit={onCommitChanges}
            />
          </div>
        </div>
        {reviewCommentStatus ? (
          <TaskDetailReviewStatus reviewStatus={reviewCommentStatus} />
        ) : null}
      </div>
    </header>
  );
}
