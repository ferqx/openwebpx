import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { fetchScmConnections, fetchScmRepositories, type ScmProvider } from '@/lib/scm';
import {
  fetchCodeReviewSettings,
  upsertCodeReviewRepositorySetting,
  updateCodeReviewGlobalSettings,
  type CodeReviewAutoReview,
  type CodeReviewProvider,
  type CodeReviewTrigger,
  type CodeReviewRepositorySetting,
  type CodeReviewWebhookSyncResult
} from '@/lib/code-review';
import {
  Search,
  GitFork,
  Info,
  Settings2,
  User,
  Loader2,
  Github,
  Gitlab
} from 'lucide-react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput
} from '@/components/ui/input-group';

type ReviewTriggerType = CodeReviewTrigger;
type AutoReviewStatus = CodeReviewAutoReview;

type RepoSource = 'github' | 'gitlab' | 'other';

type Repository = {
  key: string;
  name: string;
  source: RepoSource;
  provider: CodeReviewProvider;
  gitlabBaseUrl?: string;
  visibility: 'public' | 'private';
  autoReview: AutoReviewStatus;
  trigger: ReviewTriggerType | 'follow_global';
  lastUpdatedBy: string;
  lastUpdatedAt: string;
};

const normalizeGitlabBaseUrl = (value?: string) => {
  const trimmed = value?.trim();
  if (!trimmed) return 'https://gitlab.com';
  try {
    return new URL(trimmed).origin.toLowerCase();
  } catch {
    return trimmed.toLowerCase();
  }
};

const toCodeReviewProvider = (provider: ScmProvider): CodeReviewProvider =>
  provider === 'github' ? 'github' : 'gitlab';

const buildRepositorySettingKey = ({
  provider,
  repository,
  gitlabBaseUrl
}: {
  provider: CodeReviewProvider;
  repository: string;
  gitlabBaseUrl?: string;
}) => {
  const normalizedRepository = repository.trim().toLowerCase();
  if (provider === 'github') {
    return `github::${normalizedRepository}`;
  }
  return `gitlab::${normalizeGitlabBaseUrl(gitlabBaseUrl)}::${normalizedRepository}`;
};

const formatUpdatedAt = (value?: number) => {
  if (!value || !Number.isFinite(value)) return '-';
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false });
};

const resolveRepoSource = (provider: ScmProvider): RepoSource => {
  if (provider === 'github') return 'github';
  if (provider === 'gitlab' || provider === 'gitlab_enterprise') return 'gitlab';
  return 'other';
};

const applySettingsToRepositories = (
  repositories: Repository[],
  settings: CodeReviewRepositorySetting[]
) => {
  const settingMap = new Map<string, CodeReviewRepositorySetting>();
  settings.forEach((setting) => {
    const key = buildRepositorySettingKey({
      provider: setting.provider,
      repository: setting.repository,
      gitlabBaseUrl: setting.gitlabBaseUrl
    });
    settingMap.set(key, setting);
  });

  return repositories.map((repo) => {
    const setting = settingMap.get(repo.key);
    if (!setting) return repo;
    return {
      ...repo,
      autoReview: setting.autoReview,
      trigger: setting.trigger,
      lastUpdatedBy: setting.updatedBy?.trim() || '-',
      lastUpdatedAt: formatUpdatedAt(setting.updatedAt)
    };
  });
};

const renderWebhookSyncToast = (sync?: CodeReviewWebhookSyncResult) => {
  if (!sync) return;
  if (sync.ok && sync.enabled && sync.mode === 'auto') {
    toast.success(`${sync.provider} webhook 已自动同步`);
    return;
  }
  if (!sync.ok) {
    const manualHint = sync.manualSetup?.hint ? ` ${sync.manualSetup.hint}` : '';
    toast.warning(`${sync.message || '自动同步 webhook 失败。'}${manualHint}`.trim());
    return;
  }
  if (!sync.enabled) {
    toast.info(sync.message || '当前仓库未启用自动审查。');
  }
};

type CodeReviewSettingsProps = {
  initialSearchQuery?: string;
};

export function CodeReviewSettings({ initialSearchQuery }: CodeReviewSettingsProps) {
  const [globalAutoReview, setGlobalAutoReview] = useState(false);
  const [globalTrigger, setGlobalTrigger] = useState<ReviewTriggerType>('pr_open');

  const [isLoading, setIsLoading] = useState(true);
  const [isSavingGlobal, setIsSavingGlobal] = useState(false);
  const [savingRepoKey, setSavingRepoKey] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState(initialSearchQuery?.trim() || '');
  const [repos, setRepos] = useState<Repository[]>([]);

  const filteredRepos = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return repos;
    return repos.filter((repo) => repo.name.toLowerCase().includes(query));
  }, [repos, searchQuery]);

  useEffect(() => {
    let cancelled = false;

    const fetchPageData = async () => {
      setIsLoading(true);
      try {
        const [connections, settings] = await Promise.all([
          fetchScmConnections(),
          fetchCodeReviewSettings().catch((error) => {
            console.error('Failed to fetch code review settings', error);
            return {
              global: {
                autoReviewEnabled: false,
                defaultTrigger: 'pr_open' as CodeReviewTrigger,
                updatedAt: undefined,
                updatedBy: undefined
              },
              repositories: [] as CodeReviewRepositorySetting[]
            };
          })
        ]);

        if (cancelled) return;

        setGlobalAutoReview(settings.global.autoReviewEnabled);
        setGlobalTrigger(settings.global.defaultTrigger);

        const activeConnections = connections.filter((connection) => !connection.expired);
        if (activeConnections.length === 0) {
          setRepos([]);
          return;
        }

        const repositoryResults = await Promise.allSettled(
          activeConnections.map(async (connection) => {
            const repositories = await fetchScmRepositories({
              provider: connection.provider,
              gitlabBaseUrl: connection.gitlabBaseUrl
            });
            return repositories.map((repository) => {
              const provider = toCodeReviewProvider(connection.provider);
              const gitlabBaseUrl =
                provider === 'gitlab'
                  ? connection.provider === 'gitlab_enterprise'
                    ? normalizeGitlabBaseUrl(connection.gitlabBaseUrl)
                    : 'https://gitlab.com'
                  : undefined;

              const key = buildRepositorySettingKey({
                provider,
                repository: repository.fullName,
                gitlabBaseUrl
              });

              return {
                key,
                name: repository.fullName,
                source: resolveRepoSource(connection.provider),
                provider,
                gitlabBaseUrl,
                visibility: 'public' as const,
                autoReview: 'follow_global' as AutoReviewStatus,
                trigger: 'follow_global' as ReviewTriggerType | 'follow_global',
                lastUpdatedBy: '-',
                lastUpdatedAt: '-'
              };
            });
          })
        );

        if (cancelled) return;

        const allRepositories = repositoryResults
          .flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
          .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));

        setRepos(applySettingsToRepositories(allRepositories, settings.repositories));
      } catch (error) {
        console.error('Failed to fetch repositories for code review settings', error);
        if (!cancelled) {
          toast.error('加载代码审查配置失败，请稍后重试');
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void fetchPageData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const normalized = initialSearchQuery?.trim() || '';
    if (!normalized) return;
    setSearchQuery(normalized);
  }, [initialSearchQuery]);

  const handleGlobalAutoReviewChange = async (nextValue: boolean) => {
    if (isSavingGlobal) return;
    const previous = globalAutoReview;
    setGlobalAutoReview(nextValue);
    setIsSavingGlobal(true);
    try {
      const updated = await updateCodeReviewGlobalSettings({
        autoReviewEnabled: nextValue,
        defaultTrigger: globalTrigger
      });
      setGlobalAutoReview(updated.autoReviewEnabled);
      setGlobalTrigger(updated.defaultTrigger);
      toast.success('已更新全局自动审查设置');
    } catch (error) {
      console.error('Failed to update global auto review setting', error);
      setGlobalAutoReview(previous);
      toast.error('保存全局自动审查设置失败，请稍后重试');
    } finally {
      setIsSavingGlobal(false);
    }
  };

  const handleGlobalTriggerChange = async (nextValue: ReviewTriggerType) => {
    if (isSavingGlobal) return;
    const previous = globalTrigger;
    setGlobalTrigger(nextValue);
    setIsSavingGlobal(true);
    try {
      const updated = await updateCodeReviewGlobalSettings({
        autoReviewEnabled: globalAutoReview,
        defaultTrigger: nextValue
      });
      setGlobalAutoReview(updated.autoReviewEnabled);
      setGlobalTrigger(updated.defaultTrigger);
      toast.success('已更新全局触发器设置');
    } catch (error) {
      console.error('Failed to update global trigger', error);
      setGlobalTrigger(previous);
      toast.error('保存全局触发器失败，请稍后重试');
    } finally {
      setIsSavingGlobal(false);
    }
  };

  const handleRepoUpdate = async (
    repoKey: string,
    field: 'autoReview' | 'trigger',
    value: AutoReviewStatus | ReviewTriggerType | 'follow_global'
  ) => {
    if (savingRepoKey) return;

    const current = repos.find((repo) => repo.key === repoKey);
    if (!current) return;

    const nextRepo: Repository = {
      ...current,
      [field]: value
    } as Repository;

    const previousRepos = repos;
    setRepos((prev) => prev.map((repo) => (repo.key === repoKey ? nextRepo : repo)));
    setSavingRepoKey(repoKey);

    try {
      const response = await upsertCodeReviewRepositorySetting({
        provider: current.provider,
        repository: current.name,
        gitlabBaseUrl: current.gitlabBaseUrl,
        autoReview:
          field === 'autoReview' ? (value as AutoReviewStatus) : current.autoReview,
        trigger:
          field === 'trigger'
            ? (value as ReviewTriggerType | 'follow_global')
            : current.trigger
      });

      setRepos((prev) => applySettingsToRepositories(prev, response.repositories));
      renderWebhookSyncToast(response.webhookSync);
      toast.success('仓库代码审查设置已保存');
    } catch (error) {
      console.error('Failed to update repository review settings', error);
      setRepos(previousRepos);
      toast.error('保存仓库代码审查设置失败，请稍后重试');
    } finally {
      setSavingRepoKey(null);
    }
  };

  const getSourceIcon = (source: RepoSource) => {
    switch (source) {
      case 'github':
        return <Github className="h-4 w-4 text-muted-foreground" />;
      case 'gitlab':
        return <Gitlab className="h-4 w-4 text-muted-foreground" />;
      default:
        return <GitFork className="h-4 w-4 text-muted-foreground" />;
    }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight text-foreground">代码审查配置</h2>
        <p className="text-muted-foreground">
          管理您的个人代码审查偏好，设置全局默认规则或针对特定存储库进行微调。
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Settings2 className="h-5 w-5 text-primary" />
            <CardTitle>全局首选项</CardTitle>
          </div>
          <CardDescription>
            这些设置将应用于所有配置为“遵循个人偏好设置”的存储库。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-start gap-3 rounded-md bg-muted/50 p-4 text-sm text-muted-foreground border border-border/50">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-blue-500" />
            <p>
              当您开启全局自动审查时，AI 将默认在您创建 Pull Request 时自动介入。您可以在下方列表中覆盖特定仓库的设置。
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="flex flex-row items-center justify-between rounded-lg border p-4 shadow-sm">
              <div className="space-y-0.5">
                <Label className="text-base">启用自动代码审查</Label>
                <p className="text-xs text-muted-foreground">默认对所有新仓库生效</p>
              </div>
              <Switch
                checked={globalAutoReview}
                disabled={isSavingGlobal}
                onCheckedChange={(checked) => {
                  void handleGlobalAutoReviewChange(checked);
                }}
              />
            </div>

            <div className="flex flex-col justify-center space-y-3 rounded-lg border p-4 shadow-sm">
              <Label>默认审查触发时机</Label>
              <Select
                value={globalTrigger}
                disabled={isSavingGlobal}
                onValueChange={(value) => {
                  void handleGlobalTriggerChange(value as ReviewTriggerType);
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择触发时机" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pr_open">创建PR时</SelectItem>
                  <SelectItem value="push">每次推送时</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
            <div>
              <CardTitle>存储库设置</CardTitle>
              <CardDescription className="mt-1">为各存储库配置代码审查首选项。</CardDescription>
            </div>
            <div className="relative w-full md:w-72">
              <InputGroup className="max-w-xs">
                <InputGroupInput
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="搜索存储库"
                />
                <InputGroupAddon>
                  <Search />
                </InputGroupAddon>
              </InputGroup>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-75">存储库名称</TableHead>
                <TableHead>自动代码审查</TableHead>
                <TableHead>审查触发器</TableHead>
                <TableHead className="text-right">最后更新者</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-24 text-center">
                    <div className="flex items-center justify-center gap-2 text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在加载存储库...
                    </div>
                  </TableCell>
                </TableRow>
              ) : filteredRepos.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                    没有找到匹配的存储库
                  </TableCell>
                </TableRow>
              ) : (
                filteredRepos.map((repo) => {
                  const isSavingRow = savingRepoKey === repo.key;
                  return (
                    <TableRow key={repo.key}>
                      <TableCell className="font-medium">
                        <div className="flex items-center gap-2">
                          {getSourceIcon(repo.source)}
                          <span>{repo.name}</span>
                          {repo.visibility === 'private' && (
                            <Badge variant="outline" className="text-[10px] h-5 px-1.5">
                              Private
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Select
                          value={repo.autoReview}
                          disabled={isSavingRow || Boolean(savingRepoKey)}
                          onValueChange={(nextValue) => {
                            void handleRepoUpdate(
                              repo.key,
                              'autoReview',
                              nextValue as AutoReviewStatus
                            );
                          }}
                        >
                          <SelectTrigger className="w-50 h-8 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              <SelectItem value="follow_global">遵循个人偏好设置</SelectItem>
                              <SelectItem value="enabled">审查所有拉取请求</SelectItem>
                              <SelectItem value="disabled">禁用自动审查</SelectItem>
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell>
                        <Select
                          value={repo.trigger}
                          disabled={isSavingRow || Boolean(savingRepoKey)}
                          onValueChange={(nextValue) => {
                            void handleRepoUpdate(
                              repo.key,
                              'trigger',
                              nextValue as ReviewTriggerType | 'follow_global'
                            );
                          }}
                        >
                          <SelectTrigger className="w-45 h-8 text-sm">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              <SelectItem value="follow_global">遵循个人偏好设置</SelectItem>
                              <SelectItem value="pr_open">创建PR时</SelectItem>
                              <SelectItem value="push">每次推送时</SelectItem>
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-2 text-muted-foreground">
                          <User className="h-3.5 w-3.5" />
                          <span className="text-sm">{repo.lastUpdatedBy}</span>
                        </div>
                        <div className="text-[10px] text-muted-foreground/60">{repo.lastUpdatedAt}</div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
