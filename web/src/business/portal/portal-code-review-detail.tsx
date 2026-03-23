import React from 'react';
import { AlertCircle, ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type CodeReviewFixRequestStatus,
  type CodeReviewRunDetail
} from '@/business/portal/code-review-types';
import { PortalCodeReviewFindings } from '@/business/portal/portal-code-review-findings';
import { PortalCodeReviewSidebar } from '@/business/portal/portal-code-review-sidebar';
import { Badge } from '@/components/ui/badge';

const FIX_REQUEST_TIMELINE_STATUS: Record<string, string> = {
  fix_request_created: '待审批',
  fix_request_approved: '已批准',
  fix_request_running: '执行中',
  fix_request_completed: '已完成',
  fix_request_failed: '已失败',
  fix_request_rejected: '已拒绝'
};

const FIX_REQUEST_STATUS_LABELS: Record<CodeReviewFixRequestStatus, string> = {
  pending_approval: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
  running: '执行中',
  completed: '已完成',
  failed: '已失败'
};

const deriveFindingStatusById = (run: CodeReviewRunDetail) => {
  const fixRequestToFindingId = new Map<number, number>();
  const findingStatusById: Record<number, string> = {};

  for (const fixRequest of run.fix_requests) {
    if (fixRequest.review_finding_id === null) continue;
    findingStatusById[fixRequest.review_finding_id] =
      FIX_REQUEST_STATUS_LABELS[fixRequest.status];
  }

  for (const event of run.timeline_events) {
    const payload = event.payload ?? {};
    const fixRequestId =
      typeof payload.fix_request_id === 'number'
        ? payload.fix_request_id
        : null;
    const findingId =
      typeof payload.review_finding_id === 'number'
        ? payload.review_finding_id
        : null;

    if (fixRequestId !== null && findingId !== null) {
      fixRequestToFindingId.set(fixRequestId, findingId);
    }

    const status = FIX_REQUEST_TIMELINE_STATUS[event.event_type];
    if (!status || fixRequestId === null) continue;

    const resolvedFindingId =
      findingId ?? fixRequestToFindingId.get(fixRequestId) ?? null;
    if (
      resolvedFindingId !== null &&
      !(resolvedFindingId in findingStatusById)
    ) {
      findingStatusById[resolvedFindingId] = status;
    }
  }

  return findingStatusById;
};

type PortalCodeReviewDetailProps = {
  run: CodeReviewRunDetail | null;
  selectedRunId: number | null;
  isLoading: boolean;
  errorMessage: string | null;
  onRetry: () => void | Promise<void>;
  onBack: () => void;
  onPublishRun: (runId: number) => void | Promise<void>;
  onContinueFix: (run: CodeReviewRunDetail) => void | Promise<void>;
  onApproveFixRequest: (
    fixRequestId: number,
    runId: number
  ) => void | Promise<void>;
  onRejectFixRequest: (
    fixRequestId: number,
    runId: number
  ) => void | Promise<void>;
  canContinueFix: boolean;
  continueFixHint?: string | null;
  publishingRunIds?: Record<number, true>;
  approvingFixRequestIds?: Record<number, true>;
  rejectingFixRequestIds?: Record<number, true>;
};

function PortalCodeReviewDetailLoadingState() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border bg-card p-4">
        <div className="space-y-2">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-3 w-60" />
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(280px,0.9fr)]">
        <div className="space-y-3 rounded-xl border bg-card p-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
        <div className="space-y-3 rounded-xl border bg-card p-4">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    </div>
  );
}

export function PortalCodeReviewDetail({
  run,
  selectedRunId,
  isLoading,
  errorMessage,
  onRetry,
  onBack,
  onPublishRun,
  onContinueFix,
  onApproveFixRequest,
  onRejectFixRequest,
  canContinueFix,
  continueFixHint,
  publishingRunIds = {},
  approvingFixRequestIds = {},
  rejectingFixRequestIds = {}
}: PortalCodeReviewDetailProps) {
  const findingStatusById = run ? deriveFindingStatusById(run) : {};

  if (selectedRunId === null) {
    return null;
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Button type="button" variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="size-4" />
          返回结果列表
        </Button>
        <PortalCodeReviewDetailLoadingState />
      </div>
    );
  }

  if (errorMessage) {
    return (
      <div className="space-y-4">
        <Button type="button" variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="size-4" />
          返回结果列表
        </Button>
        <Empty className="min-h-80 border bg-card px-6 py-10">
          <EmptyMedia variant="icon">
            <AlertCircle className="size-4" />
          </EmptyMedia>
          <EmptyContent>
            <EmptyTitle>审查详情加载失败</EmptyTitle>
            <EmptyDescription>{errorMessage}</EmptyDescription>
            <Button
              type="button"
              variant="outline"
              onClick={() => void onRetry()}
            >
              重试
            </Button>
          </EmptyContent>
        </Empty>
      </div>
    );
  }

  if (run === null) {
    return null;
  }

  return (
    <div className="space-y-4 pb-12">
      {/* 顶部导航与基础信息 */}
      <div className="flex items-center justify-between gap-4">
        <Button
          className="-ml-2 h-8 text-muted-foreground hover:text-foreground"
          type="button"
          variant="ghost"
          size="sm"
          onClick={onBack}
        >
          <ArrowLeft className="mr-1.5 size-3.5" />
          返回列表
        </Button>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="h-6 px-2 text-[10px] font-normal">
            {run.provider === 'github' ? 'GitHub' : 'GitLab'}
          </Badge>
          <Badge
            variant="secondary"
            className="h-6 px-2 text-[10px] font-normal"
          >
            {run.event_type === 'merge_request' ? 'MR' : 'PR'} #
            {run.external_pr_or_mr_id ?? '未知'}
          </Badge>
        </div>
      </div>

      {/* 核心运行卡片 & 操作 */}
      <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="border-b bg-muted/30 px-4 py-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-lg font-semibold tracking-tight text-foreground">
                {run.repository?.full_name ?? '未识别仓库'}
              </h2>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>Run #{run.id}</span>
                <span>•</span>
                <span>{run.head_commit_id?.slice(0, 8) ?? '未知提交'}</span>
                <span>•</span>
                <span>{new Date(run.created_at || '').toLocaleString()}</span>
              </div>
            </div>
          </div>
        </div>

        {/* 侧边栏功能的整合：将 Sidebar 的操作部分提取到这里 */}
        <div className="p-4">
          <PortalCodeReviewSidebar
            run={run}
            onPublishRun={onPublishRun}
            onContinueFix={onContinueFix}
            onApproveFixRequest={onApproveFixRequest}
            onRejectFixRequest={onRejectFixRequest}
            canContinueFix={canContinueFix}
            continueFixHint={continueFixHint}
            publishingRunIds={publishingRunIds}
            approvingFixRequestIds={approvingFixRequestIds}
            rejectingFixRequestIds={rejectingFixRequestIds}
            layout="compact"
          />
        </div>
      </div>

      {/* 审查发现 - 全宽展示 */}
      <div className="space-y-4">
        <PortalCodeReviewFindings
          findings={run.findings}
          findingStatusById={findingStatusById}
        />
      </div>

      {/* 详细统计与时间线 - 放在底部 */}
      <div className="pt-4">
        <PortalCodeReviewSidebar
          run={run}
          onPublishRun={onPublishRun}
          onContinueFix={onContinueFix}
          onApproveFixRequest={onApproveFixRequest}
          onRejectFixRequest={onRejectFixRequest}
          canContinueFix={canContinueFix}
          continueFixHint={continueFixHint}
          publishingRunIds={publishingRunIds}
          approvingFixRequestIds={approvingFixRequestIds}
          rejectingFixRequestIds={rejectingFixRequestIds}
          layout="timeline"
        />
      </div>
    </div>
  );
}
