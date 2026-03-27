import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  type CodeReviewFixRequest,
  type CodeReviewRunDetail,
  type CodeReviewTimelineEvent
} from '@/business/portal/code-review-types';
import {
  getReviewModeMeta,
  getReviewStatusMeta
} from '@/business/portal/portal-code-review-run-card';
import { resolvePortalCodeReviewMode } from '@/hooks/use-portal-code-review-state';

const humanizeTimelineEvent = (eventType: string) => {
  const labels: Record<string, string> = {
    review_requested: '审查已请求',
    queued: '进入队列',
    analysis_started: '开始分析',
    analysis_completed: '分析完成',
    analysis_failed: '分析失败',
    fix_request_created: '已创建修复请求',
    fix_request_approved: '修复已入队',
    fix_request_running: '修复执行中',
    fix_request_completed: '修复完成',
    fix_request_failed: '修复失败',
    fix_request_rejected: '修复已拒绝',
    publish_requested: '开始发布',
    publish_completed: '发布完成'
  };
  return labels[eventType] ?? eventType;
};

const summarizeTimelinePayload = (event: CodeReviewTimelineEvent) => {
  if (!event.payload) return null;
  const entries = Object.entries(event.payload).slice(0, 2);
  if (entries.length === 0) return null;
  return entries
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(' · ');
};

export const summarizeFixRequestStates = (fixRequests: CodeReviewFixRequest[]) => {
  return fixRequests.reduce<Record<CodeReviewFixRequest['status'], number>>(
    (summary, fixRequest) => {
      summary[fixRequest.status] += 1;
      return summary;
    },
    {
      pending_approval: 0,
      approved: 0,
      rejected: 0,
      running: 0,
      completed: 0,
      failed: 0
    }
  );
};

export const getLatestTimelineEvent = (events: CodeReviewTimelineEvent[]) => {
  return [...events].sort((left, right) => {
    const leftTime = left.created_at ? Date.parse(left.created_at) : 0;
    const rightTime = right.created_at ? Date.parse(right.created_at) : 0;
    return rightTime - leftTime;
  })[0] ?? null;
};

type PortalCodeReviewSidebarProps = {
  run: CodeReviewRunDetail;
  onContinueFix: (run: CodeReviewRunDetail) => void | Promise<void>;
  onApproveFixRequest: (fixRequestId: number, runId: number) => void | Promise<void>;
  onRejectFixRequest: (fixRequestId: number, runId: number) => void | Promise<void>;
  canContinueFix: boolean;
  continueFixHint?: string | null;
  approvingFixRequestIds?: Record<number, true>;
  rejectingFixRequestIds?: Record<number, true>;
  layout?: 'full' | 'compact' | 'timeline';
};

const getFixRequestStatusMeta = (status: CodeReviewFixRequest['status']) => {
  switch (status) {
    case 'pending_approval':
      return { label: '待审批', className: 'border-amber-300 bg-amber-50 text-amber-700' };
    case 'approved':
      return { label: '排队中', className: 'border-sky-300 bg-sky-50 text-sky-700' };
    case 'running':
      return { label: '执行中', className: 'border-sky-300 bg-sky-50 text-sky-700' };
    case 'completed':
      return { label: '已完成', className: 'border-emerald-300 bg-emerald-50 text-emerald-700' };
    case 'failed':
      return { label: '已失败', className: 'border-red-300 bg-red-50 text-red-700' };
    case 'rejected':
      return { label: '已拒绝', className: 'border-border bg-muted/60 text-muted-foreground' };
  }
};

export function PortalCodeReviewSidebar({
  run,
  onContinueFix,
  onApproveFixRequest,
  onRejectFixRequest,
  canContinueFix,
  continueFixHint,
  approvingFixRequestIds = {},
  rejectingFixRequestIds = {},
  layout = 'full'
}: PortalCodeReviewSidebarProps) {
  const statusMeta = getReviewStatusMeta(run.status);
  const mode = resolvePortalCodeReviewMode(run);
  const modeMeta = getReviewModeMeta(mode);
  const showContinueFix = run.findings.length > 0 && mode === 'review_only';
  const pendingFixRequests = run.fix_requests.filter(
    (fixRequest) => fixRequest.status === 'pending_approval'
  );
  const fixRequestSummary = summarizeFixRequestStates(run.fix_requests);
  const findingsById = new Map(run.findings.map((finding) => [finding.id, finding]));
  const latestTimelineEvent = getLatestTimelineEvent(run.timeline_events);
  const timeline = [...run.timeline_events].sort((left, right) => {
    const leftTime = left.created_at ? Date.parse(left.created_at) : 0;
    const rightTime = right.created_at ? Date.parse(right.created_at) : 0;
    return leftTime - rightTime;
  });

  if (layout === 'compact') {
    return (
      <div className="space-y-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex flex-1 items-center gap-2">
            <Badge variant="outline" className={`${statusMeta.className} h-5 px-2 text-[11px]`}>
              {statusMeta.label}
            </Badge>
            <Badge variant="outline" className={`${modeMeta.className} h-5 px-2 text-[11px]`}>
              {modeMeta.label}
            </Badge>
          </div>
          {showContinueFix ? (
            <Button
              type="button"
              size="sm"
              disabled={!canContinueFix}
              onClick={() => void onContinueFix(run)}
            >
              继续修复
            </Button>
          ) : null}
        </div>

        {pendingFixRequests.length > 0 ? (
          <div className="space-y-2.5">
            <p className="text-xs font-medium text-amber-700">待处理修复请求 ({pendingFixRequests.length})</p>
            <div className="rounded-xl border bg-card">
              {pendingFixRequests.map((fixRequest) => {
                const finding = fixRequest.review_finding_id
                  ? findingsById.get(fixRequest.review_finding_id)
                  : null;
                const isApproving = Boolean(approvingFixRequestIds[fixRequest.id]);
                const isRejecting = Boolean(rejectingFixRequestIds[fixRequest.id]);
                return (
                  <div
                    key={fixRequest.id}
                    className="flex flex-col gap-2.5 border-b px-4 py-2.5 last:border-b-0 lg:flex-row lg:items-center lg:justify-between"
                  >
                    <div className="min-w-0 space-y-1">
                      <p className="line-clamp-1 text-sm font-medium text-foreground">
                        {finding?.title ?? `修复请求 #${fixRequest.id}`}
                      </p>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <span className="line-clamp-1">
                          {finding?.file_path ?? '未关联文件'}
                        </span>
                        <span>·</span>
                        <span>Fix #{fixRequest.id}</span>
                      </div>
                    </div>
                    <div className="flex gap-2 lg:w-auto">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 flex-1 bg-background text-xs lg:flex-none"
                        disabled={isApproving || isRejecting}
                        onClick={() => void onRejectFixRequest(fixRequest.id, run.id)}
                      >
                        {isRejecting ? '处理中...' : '暂不执行'}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="h-8 flex-1 text-xs lg:flex-none"
                        disabled={isApproving || isRejecting}
                        onClick={() => void onApproveFixRequest(fixRequest.id, run.id)}
                      >
                        {isApproving ? '处理中...' : '批准执行'}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  if (layout === 'timeline') {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <Card size="sm">
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-medium">运行统计</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {fixRequestSummary.pending_approval > 0 ? (
                <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-700">
                  待审批 {fixRequestSummary.pending_approval}
                </Badge>
              ) : null}
              {fixRequestSummary.running > 0 ? (
                <Badge variant="outline" className="border-sky-300 bg-sky-50 text-sky-700">
                  执行中 {fixRequestSummary.running}
                </Badge>
              ) : null}
              {fixRequestSummary.completed > 0 ? (
                <Badge variant="outline" className="border-emerald-300 bg-emerald-50 text-emerald-700">
                  已完成 {fixRequestSummary.completed}
                </Badge>
              ) : null}
              {fixRequestSummary.failed > 0 ? (
                <Badge variant="outline" className="border-red-300 bg-red-50 text-red-700">
                  已失败 {fixRequestSummary.failed}
                </Badge>
              ) : null}
            </div>

            <div className="space-y-2 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span>审查发现总数</span>
                <span className="font-medium text-foreground">{run.findings.length}</span>
              </div>
              <div className="flex justify-between">
                <span>修复请求总数</span>
                <span className="font-medium text-foreground">{run.fix_requests.length}</span>
              </div>
              <div className="flex justify-between">
                <span>Provider</span>
                <span className="font-medium text-foreground">{run.provider}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card size="sm">
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-medium">最近动态</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {timeline.slice(-3).reverse().map((event) => (
                <div key={event.id} className="relative border-l pb-4 pl-4 last:pb-0">
                  <div className="absolute -left-1 top-1 h-2 w-2 rounded-full bg-primary" />
                  <p className="text-xs font-medium text-foreground">
                    {humanizeTimelineEvent(event.event_type)}
                  </p>
                  <p className="text-[10px] text-muted-foreground">
                    {event.created_at
                      ? new Date(event.created_at).toLocaleString('zh-CN')
                      : '时间未知'}
                  </p>
                </div>
              ))}
              {timeline.length > 3 ? (
                <p className="text-[10px] text-center text-muted-foreground">查看完整时间线请访问详情</p>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Original 'full' layout (can be used for drawer or dedicated sidebar if needed)
  return (
    <div className="space-y-4">
      <Card size="sm">
        <CardHeader>
          <CardTitle>运行摘要</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className={statusMeta.className}>
              {statusMeta.label}
            </Badge>
            <Badge variant="outline" className={modeMeta.className}>
              {modeMeta.label}
            </Badge>
          </div>
          <div className="space-y-1 text-muted-foreground">
            <p>Run #{run.id}</p>
            <p>Provider {run.provider}</p>
            <p>事件 {run.event_type}</p>
            <p>提交 {(run.head_commit_id ?? '未知').slice(0, 12)}</p>
            <p>发现 {run.findings.length}</p>
            {latestTimelineEvent ? (
              <p>最近事件 {humanizeTimelineEvent(latestTimelineEvent.event_type)}</p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>待处理事项</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {pendingFixRequests.length > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50/80 p-3">
              <p className="text-sm font-medium text-amber-900">
                当前有 {pendingFixRequests.length} 项修复等待审批
              </p>
              <p className="text-xs text-amber-800">
                建议先处理审批，再决定是否继续查看完整时间线。
              </p>
            </div>
          ) : null}
          {showContinueFix ? (
            <Button
              type="button"
              className="w-full"
              disabled={!canContinueFix}
              onClick={() => void onContinueFix(run)}
            >
              继续修复
            </Button>
          ) : null}
          {pendingFixRequests.length > 0 ? (
            <div className="space-y-2">
              {pendingFixRequests.map((fixRequest) => {
                const finding = fixRequest.review_finding_id
                  ? findingsById.get(fixRequest.review_finding_id)
                  : null;
                const isApproving = Boolean(approvingFixRequestIds[fixRequest.id]);
                const isRejecting = Boolean(rejectingFixRequestIds[fixRequest.id]);
                return (
                  <div
                    key={fixRequest.id}
                    className="space-y-2 rounded-lg border bg-muted/30 p-3"
                  >
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-foreground">
                        {finding?.title ?? `修复请求 #${fixRequest.id}`}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {finding?.file_path ?? '未关联文件'}
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Button
                        type="button"
                        variant="default"
                        disabled={isApproving || isRejecting}
                        onClick={() => void onApproveFixRequest(fixRequest.id, run.id)}
                      >
                        {isApproving ? '处理中...' : '批准执行'}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        disabled={isApproving || isRejecting}
                        onClick={() => void onRejectFixRequest(fixRequest.id, run.id)}
                      >
                        {isRejecting ? '处理中...' : '暂不执行'}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
          <p className="text-xs text-muted-foreground">
            {showContinueFix && continueFixHint
              ? continueFixHint
              : '继续修复会把当前 findings 作为新提问追加到已有线程。'}
          </p>
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>修复请求</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {run.fix_requests.length === 0 ? (
            <p className="text-sm text-muted-foreground">当前没有修复请求</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {fixRequestSummary.pending_approval > 0 ? (
                  <Badge variant="outline" className="border-amber-300 bg-amber-50 text-amber-700">
                    待审批 {fixRequestSummary.pending_approval}
                  </Badge>
                ) : null}
                {fixRequestSummary.running > 0 ? (
                  <Badge variant="outline" className="border-sky-300 bg-sky-50 text-sky-700">
                    执行中 {fixRequestSummary.running}
                  </Badge>
                ) : null}
                {fixRequestSummary.completed > 0 ? (
                  <Badge variant="outline" className="border-emerald-300 bg-emerald-50 text-emerald-700">
                    已完成 {fixRequestSummary.completed}
                  </Badge>
                ) : null}
                {fixRequestSummary.failed > 0 ? (
                  <Badge variant="outline" className="border-red-300 bg-red-50 text-red-700">
                    已失败 {fixRequestSummary.failed}
                  </Badge>
                ) : null}
              </div>
              <div className="space-y-2">
                {run.fix_requests.map((fixRequest) => {
                  const status = getFixRequestStatusMeta(fixRequest.status);
                  const finding = fixRequest.review_finding_id
                    ? findingsById.get(fixRequest.review_finding_id)
                    : null;
                  return (
                    <div key={fixRequest.id} className="space-y-2 rounded-lg border p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline" className={status.className}>
                          {status.label}
                        </Badge>
                        <Badge variant="outline">Fix #{fixRequest.id}</Badge>
                      </div>
                      <div className="space-y-1 text-sm">
                        <p className="font-medium text-foreground">
                          {finding?.title ?? '未关联审查发现'}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {finding?.file_path ?? '未关联文件'}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>时间线</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">当前没有时间线事件</p>
          ) : (
            timeline.map((event) => (
              <div key={event.id} className="space-y-1 border-l pl-3">
                <p className="text-sm font-medium text-foreground">
                  {humanizeTimelineEvent(event.event_type)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {event.created_at
                    ? new Date(event.created_at).toLocaleString('zh-CN')
                    : '时间未知'}
                </p>
                {summarizeTimelinePayload(event) ? (
                  <p className="text-xs text-muted-foreground">
                    {summarizeTimelinePayload(event)}
                  </p>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
