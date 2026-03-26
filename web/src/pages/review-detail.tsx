import { PortalCodeReviewContinueFixDialog } from '@/business/portal/portal-code-review-continue-fix-dialog';
import { PortalCodeReviewDetail } from '@/business/portal/portal-code-review-detail';
import { PortalHeader } from '@/business/portal/portal-header';
import { getReviewModeMeta, getReviewStatusMeta } from '@/business/portal/portal-code-review-run-card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { usePortalCodeReviewContinuation } from '@/hooks/use-portal-code-review-continuation';
import { resolvePortalCodeReviewMode, usePortalCodeReviewState } from '@/hooks/use-portal-code-review-state';
import { mapThreadToTaskItem } from '@/lib/tasks';
import { useAuth } from '@/provider/auth';
import { useThreads } from '@/provider/thread';
import { ArrowLeft } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

export function ReviewDetailPage() {
  const navigate = useNavigate();
  const { logout } = useAuth();
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
      <div className="relative px-4 pb-8 md:px-8">
        <div className="sticky top-0 z-10 space-y-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <PortalHeader
            onLogoClick={() => navigate('/')}
            onSettingsClick={() => navigate('/settings?tab=code-review')}
            onLogout={() => logout()}
            showSettingsButton={false}
          />
        </div>

        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 pt-4">
          <section className="space-y-3">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 w-fit px-2 text-muted-foreground"
              onClick={handleBack}
            >
              <ArrowLeft className="size-4" />
              返回代码审查
            </Button>

            <div className="space-y-1">
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                代码审查详情
              </h1>
              <p className="text-sm text-muted-foreground">
                先看审查结果，再决定是否修复。
              </p>
            </div>
          </section>

          <section>
            <Card>
              <CardContent className="flex flex-col gap-3 p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-foreground">当前审查</div>
                    <div className="text-sm font-medium text-foreground">
                      {run?.repository?.full_name ?? '正在加载仓库信息'}
                    </div>
                  </div>
                  {statusMeta ? (
                    <Badge variant="outline" className={`${statusMeta.className} h-5 px-2 text-[11px]`}>
                      {statusMeta.label}
                    </Badge>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
                  {modeMeta ? (
                    <Badge variant="outline" className={`${modeMeta.className} h-5 px-2 text-[11px]`}>
                      {modeMeta.label}
                    </Badge>
                  ) : null}
                  {run?.provider ? <span>{run.provider.toUpperCase()}</span> : null}
                  <span>Review #{run?.id ?? '--'}</span>
                  <span>·</span>
                  <span>MR/PR #{run?.external_pr_or_mr_id ?? '--'}</span>
                  <span>·</span>
                  <span>{run?.findings.length ?? 0} 条发现</span>
                  <span>·</span>
                  <span>待审批修复 {pendingFixCount}</span>
                  <span>·</span>
                  {run?.thread_id ? (
                    <Button
                      type="button"
                      variant="link"
                      className="h-auto px-0 text-[13px]"
                      onClick={() => handleOpenThread(run.thread_id!)}
                    >
                      已关联线程
                    </Button>
                  ) : (
                    <span>未关联线程</span>
                  )}
                </div>
              </CardContent>
            </Card>
          </section>

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
