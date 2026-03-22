import React from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyMedia,
  EmptyTitle
} from '@/components/ui/empty';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  type CodeReviewRepositoryConfigUpdate,
  type CodeReviewRepositorySummary
} from '@/business/portal/code-review-types';

const SEVERITY_OPTIONS = ['high', 'medium', 'low', 'info'] as const;

export const readAutoFixSeverityLevels = (
  value: Record<string, unknown> | null | undefined
) => {
  const levels = value?.levels;
  if (!Array.isArray(levels)) return [] as string[];
  return levels.filter((item): item is string => typeof item === 'string');
};

export const buildAutoFixSeverityPayload = (levels: string[]) => {
  return levels.length === 0 ? null : { levels };
};

export const getCodeReviewSettingsDescription = ({
  hasSelectedRepository,
  repositoryName
}: {
  hasSelectedRepository: boolean;
  repositoryName: string;
}) =>
  hasSelectedRepository
    ? `当前仓库：${repositoryName}`
    : '请先在页面顶部选择一个仓库';

export const buildCodeReviewRepositoryEntries = ({
  repositories,
  selectedRepositoryId,
  selectedRepository,
  enabledRepositoryIds
}: {
  repositories: CodeReviewRepositorySummary[];
  selectedRepositoryId: number | null;
  selectedRepository: CodeReviewRepositorySummary | null;
  enabledRepositoryIds: Set<number>;
}) =>
  [
    ...repositories.filter((repository) => enabledRepositoryIds.has(repository.id)),
    ...(selectedRepository ? [selectedRepository] : [])
  ]
    .filter(
      (repository, index, collection) =>
        collection.findIndex((item) => item.id === repository.id) === index
    )
    .map((repository) => ({
      id: repository.id,
      provider: repository.provider,
      displayName: repository.full_name?.trim() || repository.external_repo_id,
      defaultBranch: repository.default_branch ?? null,
      isActive: repository.id === selectedRepositoryId
    }));

type PortalCodeReviewSettingsSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  repositoryName: string;
  hasSelectedRepository: boolean;
  repositories: CodeReviewRepositorySummary[];
  selectedRepositoryId: number | null;
  onSelectRepositoryId: (repositoryId: number) => void;
  enabledRepositoryIds: Set<number>;
  isLoading: boolean;
  isSaving: boolean;
  draft: CodeReviewRepositoryConfigUpdate;
  onDraftChange: (draft: CodeReviewRepositoryConfigUpdate) => void;
  onSave: () => void | Promise<void>;
};

export function PortalCodeReviewSettingsSheet({
  open,
  onOpenChange,
  repositoryName,
  hasSelectedRepository,
  repositories,
  selectedRepositoryId,
  onSelectRepositoryId,
  enabledRepositoryIds,
  isLoading,
  isSaving,
  draft,
  onDraftChange,
  onSave
}: PortalCodeReviewSettingsSheetProps) {
  const selectedLevels = readAutoFixSeverityLevels(draft.auto_fix_severities);
  const selectedRepository =
    repositories.find((repository) => repository.id === selectedRepositoryId) ?? null;
  const visibleRepositories = buildCodeReviewRepositoryEntries({
    repositories,
    selectedRepositoryId,
    selectedRepository,
    enabledRepositoryIds
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>审查设置</SheetTitle>
          <SheetDescription>
            {getCodeReviewSettingsDescription({
              hasSelectedRepository,
              repositoryName
            })}
          </SheetDescription>
        </SheetHeader>

        {visibleRepositories.length > 0 ? (
          <div className="space-y-2 px-4">
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">已接入仓库</p>
              <p className="text-xs text-muted-foreground">
                仅展示当前授权有效且已启用代码审查的仓库，可点击切换当前编辑对象。
              </p>
            </div>
            <div className="max-h-40 space-y-2 overflow-y-auto rounded-xl border bg-muted/20 p-2">
              {visibleRepositories.map((repository) => {
                return (
                  <button
                    key={repository.id}
                    className="flex w-full items-center justify-between gap-3 rounded-lg bg-background px-3 py-2 text-left"
                    type="button"
                    onClick={() => onSelectRepositoryId(repository.id)}
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground">
                        {repository.displayName}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {repository.provider}
                        {repository.defaultBranch
                          ? ` · ${repository.defaultBranch}`
                          : ''}
                      </p>
                    </div>
                    {repository.isActive ? (
                      <span className="shrink-0 rounded-full bg-primary/10 px-2 py-1 text-xs font-medium text-primary">
                        当前编辑
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {!hasSelectedRepository ? (
          <Empty className="mx-4 border bg-muted/20">
            <EmptyMedia variant="icon">!</EmptyMedia>
            <EmptyContent>
              <EmptyTitle>还没有选中仓库</EmptyTitle>
              <EmptyDescription>
                代码审查设置按仓库生效，请先选择仓库后再进行配置。
              </EmptyDescription>
            </EmptyContent>
          </Empty>
        ) : isLoading ? (
          <div className="space-y-4 px-4">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : (
          <div className="flex-1 space-y-5 overflow-y-auto px-4 pb-4">
            <div className="flex items-center justify-between gap-3 rounded-xl border bg-card p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">启用代码审查</p>
                <p className="text-xs text-muted-foreground">
                  接收 webhook 后创建审查运行并展示结果。
                </p>
              </div>
              <Switch
                checked={Boolean(draft.review_enabled)}
                onCheckedChange={(checked) =>
                  onDraftChange({ ...draft, review_enabled: checked })
                }
              />
            </div>

            <div className="flex items-center justify-between gap-3 rounded-xl border bg-card p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">启用自动修复</p>
                <p className="text-xs text-muted-foreground">
                  审查发现命中策略后自动生成修复请求。
                </p>
              </div>
              <Switch
                checked={Boolean(draft.auto_fix_enabled)}
                onCheckedChange={(checked) =>
                  onDraftChange({ ...draft, auto_fix_enabled: checked })
                }
              />
            </div>

            <div className="flex items-center justify-between gap-3 rounded-xl border bg-card p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">修复前需要审批</p>
                <p className="text-xs text-muted-foreground">
                  保留自动派生修复请求，但执行前要求显式批准。
                </p>
              </div>
              <Switch
                checked={Boolean(draft.auto_fix_requires_approval)}
                onCheckedChange={(checked) =>
                  onDraftChange({
                    ...draft,
                    auto_fix_requires_approval: checked
                  })
                }
              />
            </div>

            <div className="rounded-xl border bg-card p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">自动修复级别</p>
                <p className="text-xs text-muted-foreground">
                  仅这些严重级别的发现会自动进入修复策略。
                </p>
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {SEVERITY_OPTIONS.map((level) => {
                  const checked = selectedLevels.includes(level);
                  return (
                    <label
                      key={level}
                      className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(nextChecked) => {
                          const nextLevels = nextChecked
                            ? [...selectedLevels, level]
                            : selectedLevels.filter((item) => item !== level);
                          onDraftChange({
                            ...draft,
                            auto_fix_severities: buildAutoFixSeverityPayload(
                              nextLevels
                            )
                          });
                        }}
                      />
                      <span>{level}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3 rounded-xl border bg-card p-4">
              <div className="space-y-1">
                <p className="text-sm font-medium text-foreground">启用自动发布</p>
                <p className="text-xs text-muted-foreground">
                  分析完成后允许将审查结果自动发布到 provider。
                </p>
              </div>
              <Switch
                checked={Boolean(draft.auto_publish_enabled)}
                onCheckedChange={(checked) =>
                  onDraftChange({ ...draft, auto_publish_enabled: checked })
                }
              />
            </div>
          </div>
        )}

        <SheetFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            type="button"
            disabled={!hasSelectedRepository || isLoading || isSaving}
            onClick={() => void onSave()}
          >
            {isSaving ? '保存中...' : '保存设置'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
