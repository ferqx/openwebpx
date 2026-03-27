import { PortalCodeReviewContinueFixDialog } from '@/business/portal/portal-code-review-continue-fix-dialog';
import { PortalCodeReviewDetail } from '@/business/portal/portal-code-review-detail';
import { getReviewModeMeta, getReviewStatusMeta } from '@/business/portal/portal-code-review-run-card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { usePortalCodeReviewContinuation } from '@/hooks/use-portal-code-review-continuation';
import { resolvePortalCodeReviewMode, usePortalCodeReviewState } from '@/hooks/use-portal-code-review-state';
import { mapThreadToTaskItem } from '@/lib/tasks';
import { useThreads } from '@/provider/thread';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

export function ReviewDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const reviewId = Number(id);
  const { threads, getThreads } = useThreads();

  const codeReviewState = usePortalCodeReviewState({
    selectedRepo: '',
    enabled: true
  });

  useEffect(() => {
    void getThreads();
  }, [getThreads]);

  useEffect(() => {
    if (!Number.isFinite(reviewId) || reviewId <= 0) return;
    codeReviewState.setSelectedRunId(reviewId);
  }, [codeReviewState, reviewId]);

  const tasks = useMemo(() => threads.map(mapThreadToTaskItem), [threads]);
  const codeReviewContinuation = usePortalCodeReviewContinuation({
    tasks,
    selectedRun: codeReviewState.selectedRun,
    tab: 'review',
    navigate
  });

  const handleBack = () => {
    navigate('/', { state: { portalTab: 'review' } });
  };

  const handleOpenThread = (threadId: string) => {
    const linkedTask = tasks.find((task) => task.id === threadId);
    navigate(`/tasks/${threadId}`, {
      state: {
        portalTab: 'review',
        task: linkedTask
      }
    });
  };

  const run = codeReviewState.selectedRun;
  const statusMeta = run ? getReviewStatusMeta(run.status) : null;
  const modeMeta = run ? getReviewModeMeta(resolvePortalCodeReviewMode(run)) : null;
  const pendingFixCount = run?.fix_requests.filter(
    (fixRequest) => fixRequest.status === 'pending_approval'
  ).length ?? 0;

  return (
    <main className="relative h-full overflow-auto bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
        <div className="flex w-full flex-col gap-2 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <Button
                type="button"
                variant="ghost"
                size="icon-lg"
                aria-label="返回代码审查"
                onClick={handleBack}
              >
                <ArrowLeft className="size-5" />
              </Button>
              <Separator orientation="vertical" />
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <p className="truncate text-sm font-medium">当前审查</p>
                  <span className="text-muted-foreground">·</span>
                  <p className="truncate text-sm text-muted-foreground">
                    {run?.repository?.full_name ?? '正在加载仓库信息'}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
                  <span>Review #{run?.id ?? '--'}</span>
                  <span>·</span>
                  <span>MR/PR #{run?.external_pr_or_mr_id ?? '--'}</span>
                  {run?.provider ? (
                    <>
                      <span>·</span>
                      <span>{run.provider.toUpperCase()}</span>
                    </>
                  ) : null}
                  <span>·</span>
                  <span>{run?.findings.length ?? 0} 条发现</span>
                  <span>·</span>
                  <span>待审批修复 {pendingFixCount}</span>
                  <span>·</span>
                  {run?.thread_id ? (
                    <Button
                      type="button"
                      variant="link"
                      className="h-auto px-0 text-[13px] text-muted-foreground"
                      onClick={() => handleOpenThread(run.thread_id!)}
                    >
                      已关联线程
                    </Button>
                  ) : (
                    <span>未关联线程</span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2 pt-0.5">
              {statusMeta ? (
                <Badge variant="outline" className={`${statusMeta.className} h-5 px-2 text-[11px]`}>
                  {statusMeta.label}
                </Badge>
              ) : null}
              {modeMeta ? (
                <Badge variant="outline" className={`${modeMeta.className} h-5 px-2 text-[11px]`}>
                  {modeMeta.label}
                </Badge>
              ) : null}
            </div>
          </div>
        </div>
      </header>

      <div className="relative px-4 pb-8 pt-4 md:px-8 md:pt-6">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
          <PortalCodeReviewDetail
            run={run}
            selectedRunId={Number.isFinite(reviewId) && reviewId > 0 ? reviewId : null}
            isLoading={codeReviewState.isSelectedRunLoading}
            errorMessage={codeReviewState.selectedRunError}
            onRetry={() => codeReviewState.loadRunDetail(reviewId)}
            onContinueFix={codeReviewContinuation.handleOpenContinueFix}
            onApproveFixRequest={codeReviewState.approveFixRequest}
            onRejectFixRequest={codeReviewState.rejectFixRequest}
            canContinueFix={codeReviewContinuation.canContinueCodeReviewFix}
            continueFixHint={codeReviewContinuation.continueCodeReviewFixHint}
            approvingFixRequestIds={codeReviewState.approvingFixRequestIds}
            rejectingFixRequestIds={codeReviewState.rejectingFixRequestIds}
          />
        </div>
      </div>

      <PortalCodeReviewContinueFixDialog
        {...codeReviewContinuation.codeReviewContinueFixDialogProps}
      />
    </main>
  );
}
