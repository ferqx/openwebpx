import React from 'react';
import { AlertCircle, ClipboardList, LayoutList, Wrench } from 'lucide-react';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const FIX_REQUEST_TIMELINE_STATUS: Record<string, string> = {
  fix_request_created: '待审批',
  fix_request_approved: '已入队',
  fix_request_running: '修复执行中',
  fix_request_completed: '已完成',
  fix_request_failed: '已失败',
  fix_request_rejected: '已拒绝'
};

const FIX_REQUEST_STATUS_LABELS: Record<CodeReviewFixRequestStatus, string> = {
  pending_approval: '待审批',
  approved: '已入队',
  rejected: '已拒绝',
  running: '修复执行中',
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
  approvingFixRequestIds?: Record<number, true>;
  rejectingFixRequestIds?: Record<number, true>;
};

function PortalCodeReviewDetailLoadingState() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border bg-card p-4">
        <Skeleton className="h-10 w-full" />
      </div>
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
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
  onContinueFix,
  onApproveFixRequest,
  onRejectFixRequest,
  canContinueFix,
  continueFixHint,
  approvingFixRequestIds = {},
  rejectingFixRequestIds = {}
}: PortalCodeReviewDetailProps) {
  const findingStatusById = run ? deriveFindingStatusById(run) : {};

  if (selectedRunId === null) {
    return null;
  }

  if (isLoading) {
    return <PortalCodeReviewDetailLoadingState />;
  }

  if (errorMessage) {
    return (
      <Empty className="min-h-80 border bg-card px-6 py-10">
        <EmptyMedia variant="icon">
          <AlertCircle className="size-4" />
        </EmptyMedia>
        <EmptyContent>
          <EmptyTitle>审查加载失败</EmptyTitle>
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
    );
  }

  if (run === null) {
    return null;
  }

  const pendingFixCount = run.fix_requests.filter(r => r.status === 'pending_approval').length;

  return (
    <div className="flex h-full flex-col space-y-4 pb-6">
      <Tabs defaultValue="findings" className="w-full flex-1">
        <div className="mb-4 flex items-center justify-between">
          <TabsList className="grid w-full max-w-[320px] grid-cols-2">
            <TabsTrigger value="findings" className="flex items-center gap-1.5 text-xs sm:text-sm">
              <LayoutList className="size-3.5" />
              评审报告 ({run.findings.length})
            </TabsTrigger>
            <TabsTrigger value="fixes" className="flex items-center gap-1.5 text-xs sm:text-sm">
              <Wrench className="size-3.5" />
              修复建议
              {pendingFixCount > 0 && (
                <Badge className="ml-1 h-4 min-w-4 px-1 text-[9px]" variant="destructive">
                  {pendingFixCount}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="findings" className="mt-0 focus-visible:ring-0">
          <PortalCodeReviewFindings
            findings={run.findings}
            findingStatusById={findingStatusById}
          />
        </TabsContent>

        <TabsContent value="fixes" className="mt-0 focus-visible:ring-0">
          <div className="rounded-xl border bg-card p-4">
            <div className="mb-4 space-y-1">
              <h3 className="text-base font-semibold">修复队列</h3>
              <p className="text-sm text-muted-foreground">在这里处理待审批修复。</p>
            </div>

            <PortalCodeReviewSidebar
              run={run}
              onContinueFix={onContinueFix}
              onApproveFixRequest={onApproveFixRequest}
              onRejectFixRequest={onRejectFixRequest}
              canContinueFix={canContinueFix}
              continueFixHint={continueFixHint}
              approvingFixRequestIds={approvingFixRequestIds}
              rejectingFixRequestIds={rejectingFixRequestIds}
              layout="compact" // 这里 Sidebar 内部逻辑会自动渲染待审批列表
            />

            {run.fix_requests.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <div className="rounded-full bg-muted p-3">
                  <ClipboardList className="size-6 text-muted-foreground" />
                </div>
                <h4 className="mt-4 font-medium">暂无待修复项</h4>
                <p className="mt-1 text-sm text-muted-foreground">当前没有可处理的自动修复。</p>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
