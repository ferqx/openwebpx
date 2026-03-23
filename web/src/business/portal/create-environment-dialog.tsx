import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput
} from '@/components/ui/input-group';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';

type NetworkAccess = 'off' | 'on';

type CreateEnvironmentDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgs: string[];
  selectedOrg: string;
  onSelectedOrgChange: (org: string) => void;
  envRepoSearchId: string;
  envRepoQuery: string;
  onEnvRepoQueryChange: (value: string) => void;
  filteredEnvRepos: string[];
  selectedEnvRepo: string;
  onSelectedEnvRepoChange: (repo: string) => void;
  networkAccess: NetworkAccess;
  onNetworkAccessChange: (value: NetworkAccess) => void;
  onCreate: () => void;
};

export function CreateEnvironmentDialog({
  open,
  onOpenChange,
  orgs,
  selectedOrg,
  onSelectedOrgChange,
  envRepoSearchId,
  envRepoQuery,
  onEnvRepoQueryChange,
  filteredEnvRepos,
  selectedEnvRepo,
  onSelectedEnvRepoChange,
  networkAccess,
  onNetworkAccessChange,
  onCreate
}: CreateEnvironmentDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[90vh] overflow-auto sm:max-w-3xl"
        showCloseButton={false}
      >
        <DialogHeader>
          <DialogTitle>创建你的第一个环境</DialogTitle>
        </DialogHeader>

        <div className="space-y-5 p-1">
          <div className="space-y-2">
            <Label id="github-org-select-label">GitHub 组织</Label>
            <Select
              value={selectedOrg}
              onValueChange={(value) => onSelectedOrgChange(value)}
            >
              <SelectTrigger
                aria-labelledby="github-org-select-label"
                className="w-full"
              >
                <SelectValue placeholder="选择组织" />
              </SelectTrigger>
              <SelectContent position="popper">
                <SelectGroup>
                  {orgs.map((org) => (
                    <SelectItem key={org} value={org}>
                      {org}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor={envRepoSearchId}>存储库</Label>
            <Card>
              <CardContent>
                <InputGroup>
                  <InputGroupAddon align="inline-start">
                    <Search className="size-5 text-muted-foreground" />
                  </InputGroupAddon>
                  <InputGroupInput
                    id={envRepoSearchId}
                    value={envRepoQuery}
                    onChange={(e) => onEnvRepoQueryChange(e.target.value)}
                    placeholder="搜索"
                  />
                </InputGroup>
                <div className="mt-3 max-h-56 overflow-auto rounded-xl border p-2">
                  {filteredEnvRepos.length > 0 ? (
                    filteredEnvRepos.map((repo) => (
                      <Button
                        aria-pressed={selectedEnvRepo === repo}
                        key={repo}
                        onClick={() => onSelectedEnvRepoChange(repo)}
                        type="button"
                        variant="ghost"
                        className={cn(
                          'h-auto w-full justify-start rounded-md px-2 py-2 text-left text-sm font-normal',
                          selectedEnvRepo === repo && 'bg-muted'
                        )}
                      >
                        {repo}
                      </Button>
                    ))
                  ) : (
                    <div className="flex h-32 items-center justify-center text-base text-muted-foreground">
                      未找到存储库
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-3">
            <Label>代理网络访问</Label>
            <ToggleGroup
              type="single"
              value={networkAccess}
              onValueChange={(value) => {
                if (value === 'off' || value === 'on') onNetworkAccessChange(value);
              }}
            >
              <ToggleGroupItem value="off">关闭</ToggleGroupItem>
              <ToggleGroupItem value="on">启用</ToggleGroupItem>
            </ToggleGroup>
            <p className="text-sm text-muted-foreground md:text-base">
              设置完成后将禁用网络访问。Agent 只能使用安装脚本安装的依赖。
            </p>
          </div>
        </div>

        <DialogFooter className="sm:justify-between">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={onCreate} disabled={!selectedEnvRepo}>
            创建环境
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
