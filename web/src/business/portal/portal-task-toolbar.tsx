import { Search } from 'lucide-react';
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
import { type PortalTab } from '@/business/portal/types';

type PortalTaskToolbarProps = {
  tab: PortalTab;
  taskSearchOpen: boolean;
  onTaskSearchOpenChange: (open: boolean) => void;
  taskQuery: string;
  onTaskQueryChange: (value: string) => void;
  isTasksLoading: boolean;
  visibleTasks: TaskItem[];
  onTaskSelect: (item: TaskItem) => void;
};

export function PortalTaskToolbar({
  tab,
  taskSearchOpen,
  onTaskSearchOpenChange,
  taskQuery,
  onTaskQueryChange,
  isTasksLoading,
  visibleTasks,
  onTaskSelect
}: PortalTaskToolbarProps) {
  return (
    <div className="flex items-center justify-between">
      <TabsList variant="line">
        <TabsTrigger value="tasks">任务</TabsTrigger>
        <TabsTrigger value="review">代码审查</TabsTrigger>
      </TabsList>
      {tab === 'tasks' && (
        <Popover open={taskSearchOpen} onOpenChange={onTaskSearchOpenChange}>
          <PopoverTrigger asChild>
            <Button
              aria-label="搜索任务"
              type="button"
              variant="ghost"
              size="icon"
              disabled={isTasksLoading}
            >
              <Search />
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
      )}
    </div>
  );
}
