import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { type PortalScmSource } from '@/business/portal/types';
import { isValidScmBaseUrl, type ScmProvider } from '@/lib/scm';

type ScmOauthDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  provider: ScmProvider;
  onProviderChange: (provider: ScmProvider) => void;
  gitlabBaseUrl: string;
  onGitlabBaseUrlChange: (value: string) => void;
  isAuthorizing: boolean;
  onAuthorize: () => void;
  connectedSources: PortalScmSource[];
  isConnectionsLoading: boolean;
  revokingSourceKey: string | null;
  canRevokeSource: boolean;
  onRevokeSource: (source: PortalScmSource) => void;
};

const providerLabel: Record<ScmProvider, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  gitlab_enterprise: 'GitLab 企业版'
};

export function ScmOauthDialog({
  open,
  onOpenChange,
  provider,
  onProviderChange,
  gitlabBaseUrl,
  onGitlabBaseUrlChange,
  isAuthorizing,
  onAuthorize,
  connectedSources,
  isConnectionsLoading,
  revokingSourceKey,
  canRevokeSource,
  onRevokeSource
}: ScmOauthDialogProps) {
  const needsEnterpriseBaseUrl = provider === 'gitlab_enterprise';
  const isEnterpriseBaseUrlValid = isValidScmBaseUrl(gitlabBaseUrl);
  const isGithubProvider = provider === 'github';
  const authorizeDisabled =
    isAuthorizing ||
    (needsEnterpriseBaseUrl && !isEnterpriseBaseUrlValid);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>绑定 Git 仓库授权</DialogTitle>
          <DialogDescription>
            GitHub 使用 GitHub App 授权，GitLab 使用 OAuth2。完成后将实时加载仓库和分支列表。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>代码托管平台</Label>
            <Select
              value={provider}
              onValueChange={(value) => onProviderChange(value as ScmProvider)}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="选择平台" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="github">GitHub</SelectItem>
                <SelectItem value="gitlab">GitLab</SelectItem>
                <SelectItem value="gitlab_enterprise">GitLab 企业版</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {needsEnterpriseBaseUrl && (
            <div className="space-y-2">
              <Label htmlFor="gitlab-enterprise-base-url">
                企业 GitLab 地址
              </Label>
              <Input
                id="gitlab-enterprise-base-url"
                placeholder="https://gitlab.company.com"
                value={gitlabBaseUrl}
                onChange={(event) => onGitlabBaseUrlChange(event.target.value)}
              />
              {!isEnterpriseBaseUrlValid && gitlabBaseUrl.trim() && (
                <p className="text-xs text-destructive">
                  请输入合法的 URL（示例：`https://gitlab.company.com`）。
                </p>
              )}
            </div>
          )}
          {isGithubProvider && (
            <p className="text-xs text-muted-foreground">
              GitHub App 权限更细且更安全，建议在 GitHub 安装后授予仓库访问权限。
            </p>
          )}
          <div className="space-y-2">
            <Label>已连接来源</Label>
            {isConnectionsLoading ? (
              <p className="text-xs text-muted-foreground">正在同步连接状态...</p>
            ) : connectedSources.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                当前还没有已连接的 GitHub/GitLab 来源。
              </p>
            ) : (
              <div className="space-y-2 rounded-lg border p-2">
                {connectedSources.map((source) => (
                  <div
                    className="flex items-center justify-between gap-3 rounded-md bg-muted/40 px-3 py-2"
                    key={source.key}
                  >
                    <p className="text-sm">{source.label}</p>
                    <Button
                      disabled={Boolean(revokingSourceKey) || !canRevokeSource}
                      size="sm"
                      type="button"
                      variant="ghost"
                      onClick={() => onRevokeSource(source)}
                    >
                      {!canRevokeSource
                        ? '仅平台侧撤销'
                        : revokingSourceKey === source.key
                          ? '断开中...'
                          : '断开'}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button disabled={authorizeDisabled} onClick={onAuthorize}>
            {isAuthorizing
              ? '处理中...'
              : isGithubProvider
                ? '连接 GitHub App'
                : `授权 ${providerLabel[provider]}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
