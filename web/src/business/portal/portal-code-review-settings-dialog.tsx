import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type CodeReviewRepositoryConfig,
  type CodeReviewRepositorySummary
} from '@/business/portal/code-review-types';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';

type PortalCodeReviewSettingsDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  repositories: CodeReviewRepositorySummary[];
  configs: Record<number, CodeReviewRepositoryConfig>;
  isLoading: boolean;
  isSaving: boolean;
  onUpdateConfig: (repoId: number, update: Partial<CodeReviewRepositoryConfig>) => void;
  onSave: () => void | Promise<void>;
  onBulkUpdate: (update: Partial<CodeReviewRepositoryConfig>) => void;
};

export function PortalCodeReviewSettingsDialog({
  open,
  onOpenChange,
  repositories,
  configs,
  isLoading,
  isSaving,
  onUpdateConfig,
  onSave,
  onBulkUpdate
}: PortalCodeReviewSettingsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="!max-w-7xl w-[95vw] h-[90vh] sm:!max-w-7xl flex flex-col p-0 overflow-hidden shadow-2xl"
        showCloseButton={false}
      >
        <DialogHeader className="px-6 py-4 border-b bg-muted/20 gap-0">
          <div className="flex items-center justify-between">
            <div>
              <DialogTitle className="text-base font-semibold">仓库审查设置</DialogTitle>
              <DialogDescription className="text-xs">配置各个仓库的 AI 评审与自动修复策略。</DialogDescription>
            </div>

            <div className="flex items-center gap-4 bg-background px-3 py-1.5 rounded-lg border shadow-xs">
              <span className="text-[10px] font-semibold uppercase text-muted-foreground border-r pr-3">批量操作</span>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs">全部评审</span>
                  <Switch
                    size="sm"
                    onCheckedChange={(checked) => onBulkUpdate({ review_enabled: checked })}
                  />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs">全部修复</span>
                  <Switch
                    size="sm"
                    onCheckedChange={(checked) => onBulkUpdate({ auto_fix_enabled: checked })}
                  />
                </div>
              </div>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-hidden p-6 pb-0">
          <div className="rounded-t-lg border border-b-0 bg-background h-full flex flex-col overflow-hidden shadow-sm">
            <div className="flex-1 overflow-hidden">
              <ScrollArea className="h-full">
                <Table>
                  <TableHeader className="sticky top-0 bg-background z-10 shadow-[0_1px_0_0_rgba(0,0,0,0.1)]">
                    <TableRow className="bg-muted/30 hover:bg-muted/30">
                      <TableHead className="w-[40%] font-medium text-xs py-3">仓库路径</TableHead>
                      <TableHead className="text-center font-medium text-xs">启用 AI 评审</TableHead>
                      <TableHead className="text-center font-medium text-xs">允许自动修复</TableHead>
                      <TableHead className="text-center font-medium text-xs">修复审批</TableHead>
                      <TableHead className="text-center font-medium text-xs pr-6">自动发布</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {isLoading ? (
                      Array.from({ length: 8 }).map((_, i) => (
                        <TableRow key={i}>
                          <TableCell><Skeleton className="h-4 w-64" /></TableCell>
                          <TableCell className="text-center"><Skeleton className="h-4 w-8 mx-auto" /></TableCell>
                          <TableCell className="text-center"><Skeleton className="h-4 w-8 mx-auto" /></TableCell>
                          <TableCell className="text-center"><Skeleton className="h-4 w-8 mx-auto" /></TableCell>
                          <TableCell className="text-center pr-6"><Skeleton className="h-4 w-8 mx-auto" /></TableCell>
                        </TableRow>
                      ))
                    ) : repositories.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={5} className="h-64 text-center text-muted-foreground text-sm">
                          暂无已授权仓库
                        </TableCell>
                      </TableRow>
                    ) : (
                      repositories.map((repo) => {
                        const config = configs[repo.id];
                        return (
                          <TableRow key={repo.id} className="hover:bg-muted/10 transition-colors border-b last:border-0">
                            <TableCell className="py-4">
                              <div className="flex flex-col gap-1">
                                <span className="text-sm font-semibold text-foreground tracking-tight">{repo.full_name || repo.external_repo_id}</span>
                                <div className="flex items-center gap-2">
                                  <span className={cn(
                                    "text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-tighter border",
                                    repo.provider === 'github' ? "bg-slate-900 text-white" : "bg-orange-600 text-white"
                                  )}>
                                    {repo.provider}
                                  </span>
                                  <span className="text-[10px] text-muted-foreground font-mono">ID: {repo.id}</span>
                                </div>
                              </div>
                            </TableCell>
                            <TableCell className="text-center">
                              <Switch
                                size="sm"
                                checked={config?.review_enabled ?? false}
                                onCheckedChange={(checked) => onUpdateConfig(repo.id, { review_enabled: checked })}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Switch
                                size="sm"
                                checked={config?.auto_fix_enabled ?? false}
                                onCheckedChange={(checked) => onUpdateConfig(repo.id, { auto_fix_enabled: checked })}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Switch
                                size="sm"
                                disabled={!(config?.auto_fix_enabled)}
                                checked={config?.auto_fix_requires_approval ?? true}
                                onCheckedChange={(checked) => onUpdateConfig(repo.id, { auto_fix_requires_approval: checked })}
                              />
                            </TableCell>
                            <TableCell className="text-center pr-6">
                              <Switch
                                size="sm"
                                checked={config?.auto_publish_enabled ?? false}
                                onCheckedChange={(checked) => onUpdateConfig(repo.id, { auto_publish_enabled: checked })}
                              />
                            </TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              </ScrollArea>
            </div>
          </div>
        </div>

        {/*
            针对 UI 库 DialogFooter 样式的修正：
            底层的 DialogFooter 具有 -mx-4 -mb-4 负边距，
            我们在这里显式调整边距，确保它能出现在视野内。
        */}
        <DialogFooter className="mx-0 mb-0 border-t bg-muted/20 px-6 py-4 flex items-center gap-3">
          <Button variant="ghost" className="h-9 px-4" onClick={() => onOpenChange(false)}>
            放弃
          </Button>
          <Button
            className="h-9 px-8 font-medium rounded-lg"
            disabled={isLoading || isSaving}
            onClick={() => void onSave()}
          >
            {isSaving ? '正在应用变更...' : '保存更改'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
