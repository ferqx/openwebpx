import { getUnifiedDiffStats } from '@/business/task-detail/task-detail-utils';
import { ThreadChatDiffViewer } from '@/business/thread-chat/thread-chat-diff-viewer';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger
} from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger
} from '@/components/ui/sheet';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import {
  type SandboxThreadGitChangesResult,
  type SandboxThreadGitCommitResult
} from '@/lib/sandbox';
import { cn } from '@/lib/utils';
import {
  Check,
  FileDiff,
  FileMinus2,
  FilePenLine,
  FilePlus2,
  GitBranch,
  RefreshCw
} from 'lucide-react';
import { memo, useMemo, useState } from 'react';
import { toast } from 'sonner';

type DiffMode = 'staged' | 'unstaged';

type TaskDetailDiffSheetProps = {
  threadId?: string;
  branch?: string;
  stagedChanges: SandboxThreadGitChangesResult | null;
  unstagedChanges: SandboxThreadGitChangesResult | null;
  isLoading: boolean;
  error?: string;
  onRefresh: () => void | Promise<void>;
  onCommit: (payload: {
    message?: string;
    generateMessage: boolean;
  }) => Promise<SandboxThreadGitCommitResult>;
  className?: string;
};

type DiffSectionSummary = {
  count: number;
  added: number;
  removed: number;
  partialStats: boolean;
};

type FileChangeKind = 'added' | 'deleted' | 'modified' | 'renamed';

const getDiffSectionSummary = (
  changes: SandboxThreadGitChangesResult | null
): DiffSectionSummary => {
  if (!changes) {
    return {
      count: 0,
      added: 0,
      removed: 0,
      partialStats: false
    };
  }

  const diffStats = getUnifiedDiffStats(changes.diff);
  const hasFiles = (changes.count ?? 0) > 0;
  const hasDiff = typeof changes.diff === 'string' && changes.diff.length > 0;
  return {
    count: changes.count,
    added: diffStats.added,
    removed: diffStats.removed,
    partialStats: hasFiles && (!hasDiff || Boolean(changes.diff_truncated))
  };
};

const renderFilePath = (
  entry: NonNullable<SandboxThreadGitChangesResult['files']>[number]
) => {
  if (entry.old_path && entry.old_path !== entry.path) {
    return `${entry.old_path} -> ${entry.path}`;
  }
  return entry.path;
};

const getFileChangeKind = (
  entry: NonNullable<SandboxThreadGitChangesResult['files']>[number]
): FileChangeKind => {
  const normalized = (entry.status || '').toUpperCase();
  if (normalized === '??' || normalized.includes('A')) return 'added';
  if (normalized.includes('D')) return 'deleted';
  if (normalized.includes('R')) return 'renamed';
  return 'modified';
};

const getKindMeta = (kind: FileChangeKind) => {
  if (kind === 'added') {
    return {
      label: '新增',
      icon: FilePlus2,
      className: 'text-emerald-600'
    };
  }
  if (kind === 'deleted') {
    return {
      label: '删除',
      icon: FileMinus2,
      className: 'text-red-500'
    };
  }
  if (kind === 'renamed') {
    return {
      label: '重命名',
      icon: FilePenLine,
      className: 'text-amber-500'
    };
  }
  return {
    label: '修改',
    icon: FilePenLine,
    className: 'text-sky-500'
  };
};

const buildDiffSectionMap = (diff: string | null | undefined) => {
  const map = new Map<string, string>();
  if (!diff || !diff.trim()) return map;

  const lines = diff.split('\n');
  let chunk: string[] = [];

  const flushChunk = () => {
    if (chunk.length === 0) return;
    const content = chunk.join('\n').trim();
    if (!content) {
      chunk = [];
      return;
    }

    const firstLine = chunk[0] ?? '';
    const match = firstLine.match(/^diff --git a\/(.+?) b\/(.+)$/);
    const keys = new Set<string>();
    if (match) {
      keys.add(match[1] ?? '');
      keys.add(match[2] ?? '');
    }
    chunk.forEach((line) => {
      const renameFrom = line.match(/^rename from (.+)$/)?.[1];
      const renameTo = line.match(/^rename to (.+)$/)?.[1];
      if (renameFrom) keys.add(renameFrom);
      if (renameTo) keys.add(renameTo);
      const oldFile = line.match(/^--- a\/(.+)$/)?.[1];
      const newFile = line.match(/^\+\+\+ b\/(.+)$/)?.[1];
      if (oldFile) keys.add(oldFile);
      if (newFile) keys.add(newFile);
    });

    keys.forEach((key) => {
      const normalized = key.trim();
      if (normalized && !map.has(normalized)) {
        map.set(normalized, content);
      }
    });
    chunk = [];
  };

  lines.forEach((line) => {
    if (line.startsWith('diff --git ')) {
      flushChunk();
      chunk.push(line);
      return;
    }
    if (chunk.length > 0) {
      chunk.push(line);
    }
  });
  flushChunk();
  return map;
};

const parseDiffSectionToViewerInput = (diffSection: string | undefined) => {
  if (!diffSection?.trim()) {
    return {
      oldValue: '',
      newValue: '',
      diffHunks: undefined as
        | Array<{
            oldStart: number;
            oldCount: number;
            newStart: number;
            newCount: number;
          }>
        | undefined
    };
  }

  const oldLines: string[] = [];
  const newLines: string[] = [];
  const diffHunks: Array<{
    oldStart: number;
    oldCount: number;
    newStart: number;
    newCount: number;
  }> = [];

  diffSection.split('\n').forEach((line) => {
    const hunk = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
    if (hunk) {
      diffHunks.push({
        oldStart: Number.parseInt(hunk[1] ?? '0', 10),
        oldCount: Number.parseInt(hunk[2] ?? '1', 10),
        newStart: Number.parseInt(hunk[3] ?? '0', 10),
        newCount: Number.parseInt(hunk[4] ?? '1', 10)
      });
      return;
    }

    if (
      line.startsWith('diff --git ') ||
      line.startsWith('index ') ||
      line.startsWith('--- ') ||
      line.startsWith('+++ ') ||
      line.startsWith('old mode ') ||
      line.startsWith('new mode ') ||
      line.startsWith('new file mode ') ||
      line.startsWith('deleted file mode ') ||
      line.startsWith('similarity index ') ||
      line.startsWith('rename from ') ||
      line.startsWith('rename to ') ||
      line.startsWith('\\ No newline at end of file')
    ) {
      return;
    }

    if (line.startsWith('+') && !line.startsWith('+++')) {
      newLines.push(line.slice(1));
      return;
    }
    if (line.startsWith('-') && !line.startsWith('---')) {
      oldLines.push(line.slice(1));
      return;
    }
    if (line.startsWith(' ')) {
      const content = line.slice(1);
      oldLines.push(content);
      newLines.push(content);
      return;
    }
    oldLines.push(line);
    newLines.push(line);
  });

  return {
    oldValue: oldLines.join('\n'),
    newValue: newLines.join('\n'),
    diffHunks: diffHunks.length > 0 ? diffHunks : undefined
  };
};

export const TaskDetailDiffSheet = memo(
  ({
    threadId,
    branch,
    stagedChanges,
    unstagedChanges,
    isLoading,
    error,
    onRefresh,
    onCommit,
    className
  }: TaskDetailDiffSheetProps) => {
    const [selectedMode, setSelectedMode] = useState<DiffMode>('staged');
    const [commitMessage, setCommitMessage] = useState('');
    const [includeUnstaged, setIncludeUnstaged] = useState(false);
    const [isCommitting, setIsCommitting] = useState(false);

    const stagedSummary = useMemo(
      () => getDiffSectionSummary(stagedChanges),
      [stagedChanges]
    );
    const unstagedSummary = useMemo(
      () => getDiffSectionSummary(unstagedChanges),
      [unstagedChanges]
    );
    const selectedChanges =
      selectedMode === 'staged' ? stagedChanges : unstagedChanges;
    const selectedSummary =
      selectedMode === 'staged' ? stagedSummary : unstagedSummary;
    const selectedDiffMap = useMemo(
      () => buildDiffSectionMap(selectedChanges?.diff),
      [selectedChanges?.diff]
    );

    const commitSummary = useMemo(() => {
      if (!includeUnstaged) return stagedSummary;
      return {
        count: stagedSummary.count + unstagedSummary.count,
        added: stagedSummary.added + unstagedSummary.added,
        removed: stagedSummary.removed + unstagedSummary.removed,
        partialStats: stagedSummary.partialStats || unstagedSummary.partialStats
      };
    }, [includeUnstaged, stagedSummary, unstagedSummary]);

    const canSubmitCommit =
      Boolean(threadId) && stagedSummary.count > 0 && !isCommitting && !isLoading;

    const handleCommit = async () => {
      if (!canSubmitCommit) return;
      setIsCommitting(true);
      try {
        if (includeUnstaged && unstagedSummary.count > 0) {
          toast.info('当前提交接口仅提交已暂存变更，未暂存变更将被忽略。');
        }
        const result = await onCommit({
          message: commitMessage.trim() || undefined,
          generateMessage: commitMessage.trim().length === 0
        });
        toast.success(`提交成功：${result.commit_id.slice(0, 8)}`);
        setCommitMessage('');
      } catch (commitError) {
        const message =
          commitError instanceof Error ? commitError.message : '提交失败';
        toast.error(message || '提交失败');
      } finally {
        setIsCommitting(false);
      }
    };

    const files = selectedChanges?.files ?? [];

    return (
      <Sheet>
        <SheetTrigger asChild>
          <Button className={className} size="sm" type="button" variant="outline">
            <FileDiff className="size-4 mr-1" />
            <span className="text-xs text-muted-foreground">Staged</span>
            <span className="font-semibold text-emerald-600">
              +{stagedSummary.added}
            </span>
            <span className="font-semibold text-red-500">
              -{stagedSummary.removed}
            </span>
            <span className="mx-1 text-muted-foreground">|</span>
            <span className="text-xs text-muted-foreground">Unstaged</span>
            <span className="font-semibold text-emerald-600">
              +{unstagedSummary.added}
            </span>
            <span className="font-semibold text-red-500">
              -{unstagedSummary.removed}
            </span>
          </Button>
        </SheetTrigger>
        <SheetContent
          className="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-3xl"
          side="right"
        >
          <SheetHeader className="border-b px-4 py-3 pr-12">
            <SheetTitle>提交更改</SheetTitle>
            <SheetDescription>
              <span className="text-muted-foreground">
                列表展示为 VSCode 风格，点击文件可展开查看对应 diff。
              </span>
            </SheetDescription>
            {error ? <p className="text-xs text-destructive">{error}</p> : null}
          </SheetHeader>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
            <div className="grid grid-cols-[auto,1fr,auto] items-center gap-2 text-sm">
              <span className="text-muted-foreground">变更范围</span>
              <Select
                value={selectedMode}
                onValueChange={(value) => setSelectedMode(value as DiffMode)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="staged">已暂存</SelectItem>
                  <SelectItem value="unstaged">未暂存</SelectItem>
                </SelectContent>
              </Select>
              <Button
                disabled={isLoading}
                size="icon-sm"
                type="button"
                variant="ghost"
                onClick={() => {
                  void onRefresh();
                }}
              >
                <RefreshCw className={cn('size-4', isLoading ? 'animate-spin' : '')} />
              </Button>
            </div>

            <div className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">分支</span>
                <span className="inline-flex items-center gap-2 font-medium">
                  <GitBranch className="size-4" />
                  {branch || '--'}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">更改</span>
                <span className="inline-flex items-center gap-2">
                  <span className="text-muted-foreground">
                    {commitSummary.count} 个文件
                  </span>
                  <span className="font-semibold text-emerald-600">
                    +{commitSummary.added}
                  </span>
                  <span className="font-semibold text-red-500">
                    -{commitSummary.removed}
                  </span>
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">包含未暂存的更改</span>
                <Switch
                  checked={includeUnstaged}
                  onCheckedChange={(checked) => setIncludeUnstaged(Boolean(checked))}
                />
              </div>
              <div className="space-y-2">
                <p className="text-sm font-medium">提交消息</p>
                <Textarea
                  className="min-h-20"
                  disabled={isCommitting}
                  placeholder="留空以自动生成提交消息"
                  value={commitMessage}
                  onChange={(event) => setCommitMessage(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <p className="text-sm font-medium">后续步骤</p>
                <div className="rounded-lg border overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-2 text-sm bg-muted/30">
                    <span>提交</span>
                    <Check className="size-4 text-emerald-600" />
                  </div>
                </div>
              </div>
              <Button
                className="w-full"
                disabled={!canSubmitCommit}
                type="button"
                onClick={() => {
                  void handleCommit();
                }}
              >
                {isCommitting ? '提交中...' : '继续'}
              </Button>
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>{selectedSummary.count} 个文件</span>
                <span className="font-semibold text-emerald-600">
                  +{selectedSummary.added}
                </span>
                <span className="font-semibold text-red-500">
                  -{selectedSummary.removed}
                </span>
                {selectedSummary.partialStats ? (
                  <Badge variant="outline">统计可能不完整</Badge>
                ) : null}
                {selectedChanges?.diff_truncated ? (
                  <Badge variant="outline">Diff 已截断</Badge>
                ) : null}
              </div>

              {files.length === 0 ? (
                <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
                  当前无{selectedMode === 'staged' ? '已暂存' : '未暂存'}改动。
                </div>
              ) : (
                <Accordion className="space-y-2" collapsible type="single">
                  {files.map((entry) => {
                    const kind = getFileChangeKind(entry);
                    const kindMeta = getKindMeta(kind);
                    const StatusIcon = kindMeta.icon;
                    const diffSection =
                      selectedDiffMap.get(entry.path) ||
                      (entry.old_path ? selectedDiffMap.get(entry.old_path) : undefined);
                    const fileStats = getUnifiedDiffStats(diffSection);
                    const diffViewerInput = parseDiffSectionToViewerInput(diffSection);
                    const itemKey = `${selectedMode}-${entry.status}-${entry.path}-${entry.old_path || ''}`;

                    return (
                      <AccordionItem className="overflow-hidden rounded-lg border" key={itemKey} value={itemKey}>
                        <AccordionTrigger className="cursor-pointer px-3 py-2 hover:no-underline">
                          <div className="flex min-w-0 flex-1 items-center gap-2 pr-2">
                            <StatusIcon className={cn('size-4 shrink-0', kindMeta.className)} />
                            <span className="min-w-0 flex-1 truncate text-xs font-medium">
                              {renderFilePath(entry)}
                            </span>
                            <span className="shrink-0 text-[11px] font-semibold text-emerald-600">
                              +{fileStats.added}
                            </span>
                            <span className="shrink-0 text-[11px] font-semibold text-red-500">
                              -{fileStats.removed}
                            </span>
                            <Badge variant="outline">{kindMeta.label}</Badge>
                          </div>
                        </AccordionTrigger>
                        <AccordionContent>
                          <div className="px-3 pb-3">
                            {diffSection ? (
                              <div className="max-h-105 overflow-auto rounded-md">
                                <ThreadChatDiffViewer
                                  filePath={entry.path}
                                  oldValue={diffViewerInput.oldValue}
                                  newValue={diffViewerInput.newValue}
                                  diffLineMode="absolute"
                                  diffHunks={diffViewerInput.diffHunks}
                                />
                              </div>
                            ) : (
                              <div className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
                                该文件暂无可展示的 diff 内容。
                              </div>
                            )}
                          </div>
                        </AccordionContent>
                      </AccordionItem>
                    );
                  })}
                </Accordion>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>
    );
  }
);

TaskDetailDiffSheet.displayName = 'TaskDetailDiffSheet';
