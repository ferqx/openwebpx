import React from 'react';
import {
  CheckCircle2,
  CircleAlert,
  GitBranch,
  GitCommitVertical,
  GitPullRequest,
  LoaderCircle,
  Square,
  TriangleAlert,
  XCircle
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  type PortalCodeReviewMode,
  type PortalCodeReviewRunItem
} from '@/hooks/use-portal-code-review-state';

type PortalCodeReviewRunCardProps = {
  run: PortalCodeReviewRunItem;
  selected?: boolean;
  onSelect?: (runId: number) => void;
};

type ReviewStatusMeta = {
  label: string;
  icon: typeof LoaderCircle;
  badgeVariant: 'default' | 'secondary' | 'outline' | 'destructive';
  className: string;
};

type ReviewModeMeta = {
  label: string;
  badgeVariant: 'default' | 'secondary' | 'outline' | 'destructive';
};

const REVIEW_STATUS_META: Record<PortalCodeReviewRunItem['status'], ReviewStatusMeta> = {
  queued: {
    label: '排队中',
    icon: Square,
    badgeVariant: 'outline',
    className: 'border-border bg-background text-muted-foreground'
  },
  analyzing: {
    label: '分析中',
    icon: LoaderCircle,
    badgeVariant: 'secondary',
    className: 'border-transparent bg-secondary text-secondary-foreground'
  },
  completed: {
    label: '已完成',
    icon: CheckCircle2,
    badgeVariant: 'outline',
    className: 'border-border bg-background text-foreground'
  },
  failed: {
    label: '失败',
    icon: XCircle,
    badgeVariant: 'destructive',
    className: 'border-transparent bg-destructive/10 text-destructive'
  }
};

const REVIEW_MODE_META: Record<PortalCodeReviewMode, ReviewModeMeta> = {
  review_only: {
    label: '仅审查',
    badgeVariant: 'outline'
  },
  auto_fix_enabled: {
    label: '自动修复',
    badgeVariant: 'secondary'
  },
  pending_approval: {
    label: '待审批',
    badgeVariant: 'destructive'
  }
};

const getReviewProviderLabel = (provider: PortalCodeReviewRunItem['provider']) => {
  return provider === 'github' ? 'GitHub' : 'GitLab';
};

const getReferenceLabel = (run: PortalCodeReviewRunItem) => {
  if (!run.external_pr_or_mr_id) {
    return '未关联 PR/MR';
  }
  return `${run.provider === 'github' ? 'PR' : 'MR'} #${run.external_pr_or_mr_id}`;
};

const getShortCommitId = (commitId: string | null | undefined) => {
  if (!commitId) return '提交待同步';
  return commitId.length > 8 ? commitId.slice(0, 8) : commitId;
};

const formatCreatedAt = (value: string | null | undefined) => {
  if (!value) return '创建时间未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '创建时间未知';
  const diffMs = Date.now() - date.getTime();
  if (diffMs < 60_000) return '刚刚创建';
  const diffMinutes = Math.floor(diffMs / 60_000);
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays} 天前`;
};

export const getReviewStatusMeta = (status: PortalCodeReviewRunItem['status']) =>
  REVIEW_STATUS_META[status];

export const getReviewModeMeta = (mode: PortalCodeReviewMode | null) => {
  if (!mode) return null;
  return REVIEW_MODE_META[mode];
};

export function PortalCodeReviewRunCard({
  run,
  selected = false,
  onSelect
}: PortalCodeReviewRunCardProps) {
  const statusMeta = getReviewStatusMeta(run.status);
  const modeMeta = getReviewModeMeta(run.mode);
  const isPendingApproval = run.hasPendingApproval;
  const StatusIcon = statusMeta.icon;

  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        'group flex w-full flex-col gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:border-foreground/20 hover:bg-muted/40 focus-visible:border-ring focus-visible:ring-ring/40 focus-visible:ring-3 focus-visible:outline-none',
        selected && 'border-primary ring-1 ring-primary/20',
        isPendingApproval && 'border-destructive/40 bg-destructive/5',
        selected && isPendingApproval && 'border-destructive/60 ring-destructive/15'
      )}
      onClick={() => onSelect?.(run.id)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate font-medium text-foreground">
              {run.repositoryName || '未识别仓库'}
            </p>
            {isPendingApproval ? (
              <Badge variant="destructive" className="gap-1">
                <CircleAlert className="size-3.5" />
                待审批 {run.pendingApprovalCount}
              </Badge>
            ) : null}
          </div>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            <span>{getReviewProviderLabel(run.provider)}</span>
            <span aria-hidden="true">·</span>
            <span>{getReferenceLabel(run)}</span>
          </p>
        </div>
        <Badge
          variant={statusMeta.badgeVariant}
          className={cn(
            'gap-1.5',
            statusMeta.className,
            statusMeta.badgeVariant === 'destructive' && 'text-destructive'
          )}
        >
          <StatusIcon
            className={cn(
              'size-3.5',
              run.status === 'analyzing' && 'animate-spin'
            )}
          />
          {statusMeta.label}
        </Badge>
      </div>

      <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="inline-flex items-center gap-1">
            <GitBranch className="size-3.5" aria-hidden="true" />
            默认分支
          </span>
          <span className="text-foreground">
            {run.repositoryDefaultBranch ?? '未配置'}
          </span>
          <span aria-hidden="true">·</span>
          <span className="inline-flex items-center gap-1">
            <GitCommitVertical className="size-3.5" aria-hidden="true" />
            {getShortCommitId(run.head_commit_id)}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-start gap-2 md:justify-end">
          {typeof run.findingsCount === 'number' ? (
            <Badge variant="outline" className="gap-1">
              <TriangleAlert className="size-3.5" />
              问题 {run.findingsCount}
            </Badge>
          ) : null}
          {modeMeta ? (
            <Badge variant={modeMeta.badgeVariant} className="gap-1">
              {modeMeta.label}
            </Badge>
          ) : null}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{formatCreatedAt(run.created_at)}</span>
        <span className="inline-flex items-center gap-1">
          <GitPullRequest className="size-3.5" aria-hidden="true" />
          {selected ? '当前选中' : '点击选中'}
        </span>
      </div>
    </button>
  );
}
