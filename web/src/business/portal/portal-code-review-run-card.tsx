import {
  CheckCircle2,
  CircleAlert,
  GitPullRequest,
  LoaderCircle,
  Square,
  TriangleAlert,
  XCircle
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  type PortalCodeReviewRunItem,
  type PortalCodeReviewMode
} from '@/hooks/use-portal-code-review-state';

type PortalCodeReviewRunCardProps = {
  run: PortalCodeReviewRunItem;
  selected?: boolean;
  onSelect?: (runId: number) => void;
};

export const getReviewStatusMeta = (status: PortalCodeReviewRunItem['status']) => {
  const meta: Record<PortalCodeReviewRunItem['status'], {
    label: string;
    icon: typeof LoaderCircle;
    className: string;
    iconClassName?: string;
  }> = {
    queued: {
      label: '排队中',
      icon: Square,
      className: 'border-border bg-background text-muted-foreground'
    },
    analyzing: {
      label: '分析中',
      icon: LoaderCircle,
      className: 'border-transparent bg-secondary text-secondary-foreground',
      iconClassName: 'animate-spin'
    },
    completed: {
      label: '评审完成',
      icon: CheckCircle2,
      className: 'border-border bg-background text-foreground shadow-xs'
    },
    failed: {
      label: '评审失败',
      icon: XCircle,
      className: 'border-transparent bg-destructive/10 text-destructive'
    }
  };
  return meta[status];
};

export const getReviewModeMeta = (mode: PortalCodeReviewMode | null) => {
  switch (mode) {
    case 'pending_approval':
      return { label: '待审批', className: 'border-amber-300 bg-amber-50 text-amber-700' };
    case 'auto_fix_enabled':
      return { label: '自动修复', className: 'border-sky-300 bg-sky-50 text-sky-700' };
    case 'review_only':
      return { label: '仅审查', className: 'border-border bg-muted/60 text-muted-foreground' };
    default:
      return { label: '未知', className: 'border-border bg-muted/20 text-muted-foreground' };
  }
};

const formatShortDate = (value: string | null | undefined) => {
  if (!value) return 'N/A';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'N/A';
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

export function PortalCodeReviewRunCard({
  run,
  selected = false,
  onSelect
}: PortalCodeReviewRunCardProps) {
  const statusMeta = getReviewStatusMeta(run.status);
  const StatusIcon = statusMeta.icon;

  const title = run.repositoryName || '未知仓库';
  const reference = `${run.provider === 'github' ? 'PR' : 'MR'} #${run.external_pr_or_mr_id}`;
  const commitId = run.head_commit_id?.slice(0, 7) || 'HEAD';

  return (
    <div
      className={cn(
        'group/review-item flex items-center justify-between gap-3 p-4 border rounded-xl transition-colors',
        onSelect && 'cursor-pointer hover:bg-muted/80',
        selected && 'bg-muted border-primary/50 ring-1 ring-primary/20'
      )}
      onClick={() => onSelect?.(run.id)}
    >
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex items-center gap-2">
          <div className="rounded bg-primary/10 p-1">
            <GitPullRequest className="size-3.5 text-primary" />
          </div>
          <p className="truncate font-semibold text-sm text-foreground">
            {title} <span className="mx-1 font-normal text-muted-foreground">/</span> {reference}
          </p>
        </div>

        <div className="flex items-center gap-3 text-[11px] text-muted-foreground font-mono">
          <span className="flex items-center gap-1">
            {commitId}
          </span>
          <span className="text-muted-foreground/30">|</span>
          <span className="font-sans">{formatShortDate(run.created_at)}</span>

          {run.findingsCount !== null && run.findingsCount > 0 && (
            <>
              <span className="text-muted-foreground/30">|</span>
              <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-sans">
                <TriangleAlert className="size-3" />
                {run.findingsCount} Findings
              </span>
            </>
          )}

          {run.hasPendingApproval && (
            <>
              <span className="text-muted-foreground/30">|</span>
              <span className="flex items-center gap-1 text-destructive font-medium font-sans">
                <CircleAlert className="size-3" />
                {run.pendingApprovalCount} 待审批修复
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <Badge
          variant="outline"
          className={cn(
            'h-7 rounded-full px-2.5 text-[10px] font-medium tracking-wide uppercase',
            statusMeta.className
          )}
        >
          <StatusIcon className={cn('size-3.5 mr-1.5', statusMeta.iconClassName)} />
          {statusMeta.label}
        </Badge>
      </div>
    </div>
  );
}
