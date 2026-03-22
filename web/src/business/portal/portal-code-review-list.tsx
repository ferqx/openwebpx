import React from 'react';
import { RefreshCw, Search, SlidersHorizontal, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Empty, EmptyContent, EmptyDescription, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import {
  type PortalCodeReviewModeFilter,
  type PortalCodeReviewRunItem,
  type PortalCodeReviewStatusFilter
} from '@/hooks/use-portal-code-review-state';
import {
  PortalCodeReviewRunCard,
  getReviewModeMeta,
  getReviewStatusMeta
} from '@/business/portal/portal-code-review-run-card';

export type PortalCodeReviewListProps = {
  visibleRuns: PortalCodeReviewRunItem[];
  selectedRunId: number | null;
  onSelectRun: (runId: number) => void;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  statusFilter: PortalCodeReviewStatusFilter;
  onStatusFilterChange: (value: PortalCodeReviewStatusFilter) => void;
  modeFilter: PortalCodeReviewModeFilter;
  onModeFilterChange: (value: PortalCodeReviewModeFilter) => void;
  isLoading: boolean;
  isRefreshing: boolean;
  hasLoadedInitialData: boolean;
  emptyStateMessage: string;
  pendingApprovalCount: number;
};

type PortalCodeReviewFilterProps = Pick<
  PortalCodeReviewListProps,
  | 'searchQuery'
  | 'onSearchQueryChange'
  | 'statusFilter'
  | 'onStatusFilterChange'
  | 'modeFilter'
  | 'onModeFilterChange'
  | 'isLoading'
  | 'isRefreshing'
  | 'hasLoadedInitialData'
>;

type PortalCodeReviewResultsProps = Pick<
  PortalCodeReviewListProps,
  | 'visibleRuns'
  | 'selectedRunId'
  | 'onSelectRun'
  | 'searchQuery'
  | 'statusFilter'
  | 'modeFilter'
  | 'isLoading'
  | 'hasLoadedInitialData'
  | 'emptyStateMessage'
  | 'pendingApprovalCount'
>;

type FilterOption<TValue extends string> = {
  value: TValue;
  label: string;
};

type PortalCodeReviewQuickFilter =
  | 'all'
  | 'pending_approval'
  | 'analyzing'
  | 'completed'
  | 'failed'
  | 'review_only'
  | 'auto_fix_enabled';

const QUICK_FILTERS: FilterOption<PortalCodeReviewQuickFilter>[] = [
  { value: 'all', label: '全部结果' },
  { value: 'pending_approval', label: '待审批' },
  { value: 'analyzing', label: '分析中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'review_only', label: '仅审查' },
  { value: 'auto_fix_enabled', label: '自动修复' }
];

const hasActiveFilters = ({
  searchQuery,
  statusFilter,
  modeFilter
}: Pick<
  PortalCodeReviewListProps,
  'searchQuery' | 'statusFilter' | 'modeFilter'
>) => searchQuery.trim().length > 0 || statusFilter !== 'all' || modeFilter !== 'all';

const getSummaryText = (count: number) =>
  count === 0 ? '暂无审查结果' : `共 ${count} 条审查结果`;

const getActiveFilterText = ({
  statusFilter,
  modeFilter
}: Pick<PortalCodeReviewListProps, 'statusFilter' | 'modeFilter'>) => {
  const parts: string[] = [];
  if (statusFilter !== 'all') {
    parts.push(getReviewStatusMeta(statusFilter).label);
  }
  if (modeFilter !== 'all') {
    parts.push(getReviewModeMeta(modeFilter).label);
  }
  return parts.length > 0 ? `当前筛选：${parts.join(' / ')}` : '当前筛选：全部';
};

const resolveQuickFilter = ({
  statusFilter,
  modeFilter
}: Pick<PortalCodeReviewListProps, 'statusFilter' | 'modeFilter'>): PortalCodeReviewQuickFilter => {
  if (modeFilter === 'pending_approval') return 'pending_approval';
  if (statusFilter === 'analyzing') return 'analyzing';
  if (statusFilter === 'completed') return 'completed';
  if (statusFilter === 'failed') return 'failed';
  if (modeFilter === 'review_only') return 'review_only';
  if (modeFilter === 'auto_fix_enabled') return 'auto_fix_enabled';
  return 'all';
};

function PortalCodeReviewLoadingState() {
  return (
    <div className="grid gap-3">
      {Array.from({ length: 3 }).map((_, index) => (
        <div
          key={`review-skeleton-${index}`}
          className="rounded-xl border bg-card p-4"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-4 w-44" />
              <Skeleton className="h-3 w-72" />
            </div>
            <Skeleton className="h-5 w-20" />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-28" />
          </div>
        </div>
      ))}
    </div>
  );
}

function PortalCodeReviewEmptyState({
  message,
  hasFilters
}: {
  message: string;
  hasFilters: boolean;
}) {
  return (
    <Empty className="border border-dashed bg-muted/20 px-6 py-10">
      <EmptyMedia variant="icon">
        {hasFilters ? <Search className="size-4" /> : <Sparkles className="size-4" />}
      </EmptyMedia>
      <EmptyContent>
        <EmptyTitle>{hasFilters ? '没有匹配条件的审查运行' : '当前仓库还没有审查运行'}</EmptyTitle>
        <EmptyDescription>{message}</EmptyDescription>
      </EmptyContent>
    </Empty>
  );
}

export function PortalCodeReviewFilters({
  searchQuery,
  onSearchQueryChange,
  statusFilter,
  onStatusFilterChange,
  modeFilter,
  onModeFilterChange,
  isLoading,
  isRefreshing,
  hasLoadedInitialData
}: PortalCodeReviewFilterProps) {
  const activeFilters = hasActiveFilters({ searchQuery, statusFilter, modeFilter });
  const showLoadingState = isLoading || !hasLoadedInitialData;
  const statusMeta = statusFilter === 'all' ? null : getReviewStatusMeta(statusFilter);
  const modeMeta = modeFilter === 'all' ? null : getReviewModeMeta(modeFilter);
  const quickFilter = resolveQuickFilter({ statusFilter, modeFilter });

  return (
    <div className="rounded-xl border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-base font-medium text-foreground">筛选条件</h2>
          <p className="text-sm text-muted-foreground">
            在当前仓库范围内筛选审查结果，快速定位待处理运行。
          </p>
        </div>
        {isRefreshing && hasLoadedInitialData ? (
          <Badge variant="secondary" className="gap-1">
            <RefreshCw className="size-3.5 animate-spin" />
            正在同步
          </Badge>
        ) : null}
      </div>

      <Separator className="my-4" />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="space-y-1.5">
          <Label htmlFor="portal-review-search">搜索</Label>
          <div className="relative">
            <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
            <Input
              id="portal-review-search"
              className="pl-9"
              disabled={showLoadingState}
              placeholder="搜索仓库、PR/MR、提交或事件"
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="portal-review-quick-filter">快速筛选</Label>
          <Select
            value={quickFilter}
            onValueChange={(value) => {
              const next = value as PortalCodeReviewQuickFilter;
              if (next === 'pending_approval') {
                onStatusFilterChange('all');
                onModeFilterChange('pending_approval');
                return;
              }
              if (next === 'review_only') {
                onStatusFilterChange('all');
                onModeFilterChange('review_only');
                return;
              }
              if (next === 'auto_fix_enabled') {
                onStatusFilterChange('all');
                onModeFilterChange('auto_fix_enabled');
                return;
              }
              if (next === 'analyzing' || next === 'completed' || next === 'failed') {
                onStatusFilterChange(next as PortalCodeReviewStatusFilter);
                onModeFilterChange('all');
                return;
              }
              onStatusFilterChange('all');
              onModeFilterChange('all');
            }}
          >
            <SelectTrigger id="portal-review-quick-filter" className="w-full" size="sm">
              <SelectValue placeholder="全部结果" />
            </SelectTrigger>
            <SelectContent>
              {QUICK_FILTERS.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {(statusMeta || modeMeta || activeFilters) ? (
        <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
          {statusMeta ? (
            <Badge variant={statusMeta.badgeVariant} className={cn('gap-1', statusMeta.className)}>
              {statusMeta.label}
            </Badge>
          ) : null}
          {modeMeta ? (
            <Badge variant={modeMeta.badgeVariant} className="gap-1">
              {modeMeta.label}
            </Badge>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function PortalCodeReviewList({
  visibleRuns,
  selectedRunId,
  onSelectRun,
  searchQuery,
  statusFilter,
  modeFilter,
  isLoading,
  hasLoadedInitialData,
  emptyStateMessage,
  pendingApprovalCount
}: PortalCodeReviewResultsProps) {
  const activeFilters = hasActiveFilters({ searchQuery, statusFilter, modeFilter });
  const showLoadingState = isLoading || !hasLoadedInitialData;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 px-1 text-sm text-muted-foreground">
        <Badge variant="outline" className="gap-1">
          <SlidersHorizontal className="size-3.5" />
          {getSummaryText(visibleRuns.length)}
        </Badge>
        {pendingApprovalCount > 0 ? (
          <Badge variant="destructive" className="gap-1">
            <Sparkles className="size-3.5" />
            待审批 {pendingApprovalCount}
          </Badge>
        ) : null}
        <span>{getActiveFilterText({ statusFilter, modeFilter })}</span>
      </div>

      {showLoadingState ? (
        <PortalCodeReviewLoadingState />
      ) : visibleRuns.length === 0 ? (
        <PortalCodeReviewEmptyState
          hasFilters={activeFilters}
          message={emptyStateMessage}
        />
      ) : (
        <div className="grid gap-3">
          {visibleRuns.map((run) => (
            <PortalCodeReviewRunCard
              key={run.id}
              run={run}
              selected={selectedRunId === run.id}
              onSelect={onSelectRun}
            />
          ))}
        </div>
      )}
    </div>
  );
}
