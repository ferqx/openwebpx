import { useMemo, useState } from 'react';
import { ChevronsUpDown, GitBranch } from 'lucide-react';
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
import { PromptInputButton } from '@/components/ai-elements/prompt-input';
import { cn } from '@/lib/utils';

type PortalBranchPickerProps = {
  selectedRepo: string;
  selectedBranch: string;
  branchOptions: string[];
  isBranchLoading: boolean;
  onSelectBranch: (branch: string) => void;
};

export function PortalBranchPicker({
  selectedRepo,
  selectedBranch,
  branchOptions,
  isBranchLoading,
  onSelectBranch
}: PortalBranchPickerProps) {
  const [branchPickerOpen, setBranchPickerOpen] = useState(false);
  const [branchQuery, setBranchQuery] = useState('');
  const [branchListHovered, setBranchListHovered] = useState(false);

  const filteredBranches = useMemo(() => {
    const query = branchQuery.trim().toLowerCase();
    if (!query) return branchOptions;
    return branchOptions.filter((branch) =>
      branch.toLowerCase().includes(query)
    );
  }, [branchOptions, branchQuery]);

  return (
    <Popover
      open={branchPickerOpen}
      onOpenChange={(open) => {
        setBranchPickerOpen(open);
        if (!open) setBranchQuery('');
        setBranchListHovered(false);
      }}
    >
      <PopoverTrigger asChild>
        <PromptInputButton
          aria-expanded={branchPickerOpen}
          aria-label="选择分支"
          className="max-w-44 justify-between text-muted-foreground hover:text-foreground"
          disabled={!selectedRepo}
          role="combobox"
          type="button"
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <GitBranch className="size-4 shrink-0" />
            <span className="truncate">
              {selectedBranch || (isBranchLoading ? '加载分支中...' : '选择分支')}
            </span>
          </span>
          <ChevronsUpDown className="size-4 opacity-60" />
        </PromptInputButton>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-60 p-0">
        <Command>
          <CommandInput
            placeholder="搜索分支..."
            value={branchQuery}
            onValueChange={setBranchQuery}
          />
          <CommandList onMouseLeave={() => setBranchListHovered(false)}>
            <CommandEmpty>
              {isBranchLoading ? '正在加载分支...' : '未找到分支'}
            </CommandEmpty>
            <CommandGroup>
              {filteredBranches.map((branch) => (
                <CommandItem
                  className={cn(
                    !branchListHovered &&
                      'data-selected:bg-transparent data-selected:text-foreground',
                    selectedBranch === branch && 'font-medium'
                  )}
                  data-checked={selectedBranch === branch}
                  key={branch}
                  value={branch}
                  onMouseMove={() => setBranchListHovered(true)}
                  onSelect={() => {
                    onSelectBranch(branch);
                    setBranchPickerOpen(false);
                    setBranchQuery('');
                    setBranchListHovered(false);
                  }}
                >
                  <span className="truncate">{branch}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
