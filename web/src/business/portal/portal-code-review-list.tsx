import React from 'react';
import { Search, Sparkles } from 'lucide-react';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type PortalCodeReviewModeFilter,
  type PortalCodeReviewRunItem,
  type PortalCodeReviewStatusFilter
} from '@/hooks/use-portal-code-review-state';
import { PortalCodeReviewRunCard } from '@/business/portal/portal-code-review-run-card';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput
} from '@/components/ui/input-group';

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
  | 'isLoading'
  | 'hasLoadedInitialData'
  | 'emptyStateMessage'
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

const resolveQuickFilter = ({
  statusFilter,
  modeFilter
}: Pick<
  PortalCodeReviewListProps,
  'statusFilter' | 'modeFilter'
>): PortalCodeReviewQuickFilter => {
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
        <div key={`review-skeleton-${index}`} className="rounded-xl border p-4">
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
    <Empty className="border border-dashed px-6 py-10">
      <EmptyMedia variant="icon">
        {hasFilters ? (
          <Search className="size-4" />
        ) : (
          <Sparkles className="size-4" />
        )}
      </EmptyMedia>
      <EmptyContent>
        <EmptyTitle>
          {hasFilters ? '没有匹配条件的审查运行' : '当前仓库还没有审查运行'}
        </EmptyTitle>
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
  isLoading
}: PortalCodeReviewFilterProps) {
  const showLoadingState = isLoading;
  const quickFilter = resolveQuickFilter({ statusFilter, modeFilter });

  return (
    <div className="py-1">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[160px]">
          <InputGroup>
            <InputGroupInput
              disabled={showLoadingState}
              placeholder="搜索审查结果..."
              value={searchQuery}
              onChange={(event) => onSearchQueryChange(event.target.value)}
            />
            <InputGroupAddon>
              <Search />
            </InputGroupAddon>
          </InputGroup>
        </div>
        <div className="shrink-0">
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
              if (
                next === 'analyzing' ||
                next === 'completed' ||
                next === 'failed'
              ) {
                onStatusFilterChange(next as PortalCodeReviewStatusFilter);
                onModeFilterChange('all');
                return;
              }
              onStatusFilterChange('all');
              onModeFilterChange('all');
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder="筛选" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {QUICK_FILTERS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}

export function PortalCodeReviewList({
  visibleRuns,
  selectedRunId,
  onSelectRun,
  isLoading,
  hasLoadedInitialData,
  emptyStateMessage
}: PortalCodeReviewResultsProps) {
  const showLoadingState = isLoading || !hasLoadedInitialData;

  return (
    <div className="space-y-3">
      {showLoadingState ? (
        <PortalCodeReviewLoadingState />
      ) : visibleRuns.length === 0 ? (
        <PortalCodeReviewEmptyState
          hasFilters={false}
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
