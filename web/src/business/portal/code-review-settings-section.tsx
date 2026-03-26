import { useEffect, useMemo, useState } from 'react';
import { Lock, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import {
  type CodeReviewRepositoryConfig,
  type CodeReviewRepositoryConfigUpdate,
  type CodeReviewRepositorySummary
} from '@/business/portal/code-review-types';
import { usePortalCodeReviewState } from '@/hooks/use-portal-code-review-state';
import { updateCodeReviewRepositoryConfig } from '@/lib/code-review';
import { cn } from '@/lib/utils';

type AuthorizedRepository = {
  id: number;
  provider: CodeReviewRepositorySummary['provider'];
  config_key: string;
  repository_identity_key: string;
  full_name: string;
  default_branch: string | null | undefined;
};

const DEFAULT_REPOSITORY_CONFIG: CodeReviewRepositoryConfigUpdate = {
  review_enabled: true,
  auto_fix_enabled: false,
  auto_fix_requires_approval: true,
  auto_publish_enabled: false
};

type RepositoryConfigSource = Partial<
  CodeReviewRepositorySummary & CodeReviewRepositoryConfig
>;

const getOptionalBoolean = (
  source: RepositoryConfigSource | undefined,
  key: 'auto_fix_enabled' | 'auto_fix_requires_approval' | 'auto_publish_enabled'
) => {
  const value = source ? (source as Record<string, unknown>)[key] : undefined;
  return typeof value === 'boolean' ? value : undefined;
};

const toRepositoryConfig = (
  source?: RepositoryConfigSource
): CodeReviewRepositoryConfigUpdate => ({
  review_enabled: source?.review_enabled ?? DEFAULT_REPOSITORY_CONFIG.review_enabled,
  auto_fix_enabled:
    getOptionalBoolean(source, 'auto_fix_enabled') ??
    DEFAULT_REPOSITORY_CONFIG.auto_fix_enabled,
  auto_fix_requires_approval:
    getOptionalBoolean(source, 'auto_fix_requires_approval') ??
    DEFAULT_REPOSITORY_CONFIG.auto_fix_requires_approval,
  auto_publish_enabled:
    getOptionalBoolean(source, 'auto_publish_enabled') ??
    DEFAULT_REPOSITORY_CONFIG.auto_publish_enabled
});

export function CodeReviewSettingsSection() {
  const codeReviewState = usePortalCodeReviewState({
    selectedRepo: '',
    enabled: true
  });

  const authorizedRepositories = useMemo<AuthorizedRepository[]>(
    () =>
      codeReviewState.repositories
        .filter(
          (repository): repository is CodeReviewRepositorySummary & {
            repository_identity_key: string;
          } => Boolean(repository.repository_identity_key)
        )
        .map((repository) => ({
          id: repository.id,
          provider: repository.provider,
          config_key: String(repository.id),
          repository_identity_key: repository.repository_identity_key,
          full_name: repository.full_name?.trim() || repository.external_repo_id,
          default_branch: repository.default_branch
        })),
    [codeReviewState.repositories]
  );

  const [configs, setConfigs] = useState<
    Record<string, CodeReviewRepositoryConfigUpdate>
  >({});
  const [savingRows, setSavingRows] = useState<Record<string, boolean>>({});
  const [repositoryQuery, setRepositoryQuery] = useState('');

  useEffect(() => {
    if (!codeReviewState.hasLoadedInitialData) return;

    setConfigs((prev) => {
      const next = { ...prev };
      authorizedRepositories.forEach((repo) => {
        const source = codeReviewState.repositories.find(
          (item) => item.id === repo.id
        );
        next[repo.config_key] = {
          ...DEFAULT_REPOSITORY_CONFIG,
          ...toRepositoryConfig(source),
          ...prev[repo.config_key]
        };
      });
      return next;
    });
  }, [
    authorizedRepositories,
    codeReviewState.hasLoadedInitialData,
    codeReviewState.repositories
  ]);

  const visibleRepositories = useMemo(() => {
    const query = repositoryQuery.trim().toLowerCase();
    if (!query) return authorizedRepositories;
    return authorizedRepositories.filter((repo) => {
      const candidates = [
        repo.full_name,
        repo.repository_identity_key,
        repo.default_branch ?? '',
        repo.provider
      ];
      return candidates.some((value) => value.toLowerCase().includes(query));
    });
  }, [authorizedRepositories, repositoryQuery]);

  const handleRealtimeUpdate = async (
    repoKey: string,
    update: CodeReviewRepositoryConfigUpdate
  ) => {
    const previousConfig = configs[repoKey] ?? DEFAULT_REPOSITORY_CONFIG;
    const nextConfig = {
      ...DEFAULT_REPOSITORY_CONFIG,
      ...previousConfig,
      ...update
    };

    setConfigs((prev) => ({ ...prev, [repoKey]: nextConfig }));
    setSavingRows((prev) => ({ ...prev, [repoKey]: true }));

    const repo = authorizedRepositories.find((item) => item.config_key === repoKey);

    if (!repo) {
      setConfigs((prev) => ({ ...prev, [repoKey]: previousConfig }));
      setSavingRows((prev) => ({ ...prev, [repoKey]: false }));
      toast.error('当前仓库尚未同步到代码审查配置，无法保存。');
      return;
    }

    try {
      const saved = await updateCodeReviewRepositoryConfig(repo.id, nextConfig);
      setConfigs((prev) => ({
        ...prev,
        [repoKey]: {
          ...DEFAULT_REPOSITORY_CONFIG,
          ...toRepositoryConfig(saved)
        }
      }));
    } catch (error) {
      console.error('Failed to update repository config', error);
      setConfigs((prev) => ({ ...prev, [repoKey]: previousConfig }));
      toast.error('保存仓库配置失败，请稍后重试');
    } finally {
      setSavingRows((prev) => ({ ...prev, [repoKey]: false }));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <span>全部仓库直接展示</span>
        <span>切换后即时保存</span>
        <span>失败自动回滚</span>
        <span>共 {authorizedRepositories.length} 个仓库</span>
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex flex-col gap-3 border-b sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-1">
            <CardTitle className="text-base">仓库配置</CardTitle>
            <CardDescription>
              直接查看全部仓库，并对单个仓库即时调整代码审查策略。
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Input
              value={repositoryQuery}
              onChange={(event) => setRepositoryQuery(event.target.value)}
              placeholder="搜索仓库"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5 text-xs"
              onClick={() => codeReviewState.refresh()}
            >
              <RefreshCw
                className={cn(
                  'size-3.5',
                  codeReviewState.isRefreshing && 'animate-spin'
                )}
              />
              刷新列表
            </Button>
          </div>
        </CardHeader>

        <ScrollArea className="max-h-[calc(100vh-21rem)]">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-background/95">
              <TableRow>
                <TableHead className="w-[40%] pl-6">仓库</TableHead>
                <TableHead className="text-center">启用评审</TableHead>
                <TableHead className="text-center">自动修复</TableHead>
                <TableHead className="text-center">审批</TableHead>
                <TableHead className="pr-6 text-center">自动发布</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!codeReviewState.hasLoadedInitialData ? (
                Array.from({ length: 8 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell className="pl-6">
                      <Skeleton className="h-5 w-52" />
                    </TableCell>
                    <TableCell colSpan={4}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              ) : visibleRepositories.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-52">
                    <div className="flex flex-col items-center justify-center gap-2 text-center text-muted-foreground">
                      <Lock className="size-9 opacity-40" />
                      <p className="text-sm font-medium text-foreground">
                        未找到匹配的仓库
                      </p>
                      <p className="text-sm text-muted-foreground">
                        调整搜索条件后再试。
                      </p>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                visibleRepositories.map((repo) => {
                  const config = configs[repo.config_key] ?? DEFAULT_REPOSITORY_CONFIG;
                  const isSaving = savingRows[repo.config_key] ?? false;

                  return (
                    <TableRow
                      key={repo.repository_identity_key}
                      className="hover:bg-muted/30"
                    >
                      <TableCell className="pl-6 py-3">
                        <div className="flex flex-col gap-1">
                          <div className="text-sm font-medium text-foreground">
                            {repo.full_name}
                          </div>
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <Badge variant="outline" className="capitalize">
                              {repo.provider}
                            </Badge>
                            <span>{repo.repository_identity_key}</span>
                            {repo.default_branch ? (
                              <span>默认分支 {repo.default_branch}</span>
                            ) : null}
                            {isSaving ? <span className="opacity-70">保存中</span> : null}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        <Switch
                          checked={config.review_enabled ?? false}
                          disabled={isSaving}
                          onCheckedChange={(checked) =>
                            handleRealtimeUpdate(repo.config_key, {
                              review_enabled: checked
                            })
                          }
                        />
                      </TableCell>
                      <TableCell className="text-center">
                        <Switch
                          checked={config.auto_fix_enabled ?? false}
                          disabled={isSaving}
                          onCheckedChange={(checked) =>
                            handleRealtimeUpdate(repo.config_key, {
                              auto_fix_enabled: checked
                            })
                          }
                        />
                      </TableCell>
                      <TableCell className="text-center">
                        <Switch
                          checked={config.auto_fix_requires_approval ?? true}
                          disabled={isSaving || !config.auto_fix_enabled}
                          onCheckedChange={(checked) =>
                            handleRealtimeUpdate(repo.config_key, {
                              auto_fix_requires_approval: checked
                            })
                          }
                        />
                      </TableCell>
                      <TableCell className="pr-6 text-center">
                        <Switch
                          checked={config.auto_publish_enabled ?? false}
                          disabled={isSaving}
                          onCheckedChange={(checked) =>
                            handleRealtimeUpdate(repo.config_key, {
                              auto_publish_enabled: checked
                            })
                          }
                        />
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </ScrollArea>
      </Card>
    </div>
  );
}
