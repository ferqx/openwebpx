import { useMemo, useState } from 'react';
import { Filter, Search, Settings2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from '@/components/ui/command';
import {
  Popover,
  PopoverContent,
  PopoverTrigger
} from '@/components/ui/popover';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';
import { type TaskItem } from '@/lib/tasks';
import { portalTabs, type PortalTab, type PortalScmRepositoryOption } from '@/business/portal/types';
import { cn } from '@/lib/utils';

type PortalTaskToolbarProps = {
  tab: PortalTab;
  taskSearchOpen: boolean;
  onTaskSearchOpenChange: (open: boolean) => void;
  taskQuery: string;
  onTaskQueryChange: (value: string) => void;
  isTasksLoading: boolean;
  visibleTasks: TaskItem[];
  onTaskSelect: (item: TaskItem) => void;
  onReviewSettingsClick: () => void;

  // 仓库过滤相关
  reviewRepoOptions?: PortalScmRepositoryOption[];
  selectedReviewRepoKey?: string;
  onReviewRepoSelect?: (key: string) => void;
  onReviewRepoClear?: () => void;
};

export function PortalTaskToolbar({
  tab,
  taskSearchOpen,
  onTaskSearchOpenChange,
  taskQuery,
  onTaskQueryChange,
  isTasksLoading,
  visibleTasks,
  onTaskSelect,
  onReviewSettingsClick,
  reviewRepoOptions = [],
  selectedReviewRepoKey,
  onReviewRepoSelect,
  onReviewRepoClear
}: PortalTaskToolbarProps) {
  const [repoFilterOpen, setRepoFilterOpen] = useState(false);
  const [repoQuery, setRepoQuery] = useState('');

  const selectedRepoName = useMemo(() => {
    if (!selectedReviewRepoKey) return null;
    return reviewRepoOptions.find(r => r.key === selectedReviewRepoKey)?.fullName;
  }, [selectedReviewRepoKey, reviewRepoOptions]);

  const filteredRepos = useMemo(() => {
    const q = repoQuery.trim().toLowerCase();
    if (!q) return reviewRepoOptions;
    return reviewRepoOptions.filter(r => r.fullName.toLowerCase().includes(q));
  }, [repoQuery, reviewRepoOptions]);

  return (
    <div className="flex items-center justify-between">
      <TabsList variant="line">
        {portalTabs.map((portalTab) => (
          <TabsTrigger key={portalTab} value={portalTab}>
            {portalTab === 'tasks' ? '任务' : '代码审查'}
          </TabsTrigger>
        ))}
      </TabsList>

      <div className="flex items-center gap-1">
        {tab === 'tasks' ? (
          <Popover open={taskSearchOpen} onOpenChange={onTaskSearchOpenChange}>
            <PopoverTrigger asChild>
              <Button
                aria-label="搜索任务"
                type="button"
                variant="ghost"
                size="icon"
                disabled={isTasksLoading}
              >
                <Search className="size-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-75 p-0">
              <Command>
                <CommandInput
                  placeholder="搜索任务..."
                  value={taskQuery}
                  onValueChange={onTaskQueryChange}
                />
                <CommandList>
                  <CommandEmpty>
                    {isTasksLoading ? '正在加载任务...' : '未找到任务'}
                  </CommandEmpty>
                  <CommandGroup>
                    {visibleTasks.map((item) => (
                      <CommandItem
                        key={item.id}
                        value={item.id}
                        keywords={[item.title, item.repo, item.branch]}
                        onSelect={() => onTaskSelect(item)}
                      >
                        <div className="min-w-0">
                          <p className="truncate">{item.title}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {item.repo} · {item.branch}
                          </p>
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        ) : (
          <>
            {/* 仓库选择过滤器 */}
            <Popover open={repoFilterOpen} onOpenChange={setRepoFilterOpen}>
              <PopoverTrigger asChild>
                <Button
                  aria-label="筛选仓库"
                  type="button"
                  variant={selectedReviewRepoKey ? "secondary" : "ghost"}
                  size={selectedReviewRepoKey ? "default" : "icon"}
                  className={cn("h-8 gap-1.5", selectedReviewRepoKey && "pl-2 pr-1 text-xs max-w-40")}
                >
                  <Filter className="size-4" />
                  {selectedRepoName && <span className="truncate">{selectedRepoName}</span>}
                  {selectedReviewRepoKey && (
                    <div
                      role="button"
                      className="ml-1 rounded-full p-0.5 hover:bg-muted-foreground/20"
                      onClick={(e) => {
                        e.stopPropagation();
                        onReviewRepoClear?.();
                      }}
                    >
                      <X className="size-3" />
                    </div>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-70 p-0">
                <Command>
                  <CommandInput
                    placeholder="按仓库筛选..."
                    value={repoQuery}
                    onValueChange={setRepoQuery}
                  />
                  <CommandList>
                    <CommandEmpty>未找到仓库</CommandEmpty>
                    <CommandGroup>
                      {/* 清除筛选选项 */}
                      <CommandItem
                        value="__all__"
                        onSelect={() => {
                          onReviewRepoClear?.();
                          setRepoFilterOpen(false);
                        }}
                      >
                        显示全部仓库
                      </CommandItem>
                      {filteredRepos.map((repo) => (
                        <CommandItem
                          key={repo.key}
                          value={repo.key}
                          onSelect={() => {
                            onReviewRepoSelect?.(repo.key);
                            setRepoFilterOpen(false);
                          }}
                        >
                          <div className="min-w-0">
                            <p className="truncate text-xs font-medium">{repo.fullName}</p>
                            <p className="text-[10px] text-muted-foreground uppercase">{repo.source.label}</p>
                          </div>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>

            <Button
              aria-label="审查设置"
              type="button"
              variant="ghost"
              size="icon"
              onClick={onReviewSettingsClick}
            >
              <Settings2 className="size-4" />
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
