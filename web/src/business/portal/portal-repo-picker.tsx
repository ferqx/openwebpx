import { useMemo, useState } from 'react';
import { ChevronsUpDown, FolderGit2, Settings } from 'lucide-react';
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
import { PromptInputButton } from '@/components/ai-elements/prompt-input';
import { type PortalScmRepositoryOption } from '@/business/portal/types';
import { cn } from '@/lib/utils';

type PortalRepoPickerProps = {
  selectedRepoKey: string;
  selectedRepo: string;
  repositoryOptions: PortalScmRepositoryOption[];
  isRepositoryLoading: boolean;
  repositoryEmptyMessage: string;
  onSelectRepoKey: (key: string) => void;
  onOpenScmAuthDialog: () => void;
  onRefreshRepositories: () => void;
};

export function PortalRepoPicker({
  selectedRepoKey,
  selectedRepo,
  repositoryOptions,
  isRepositoryLoading,
  repositoryEmptyMessage,
  onSelectRepoKey,
  onOpenScmAuthDialog,
  onRefreshRepositories
}: PortalRepoPickerProps) {
  const [repoPickerOpen, setRepoPickerOpen] = useState(false);
  const [repoQuery, setRepoQuery] = useState('');
  const [repoListHovered, setRepoListHovered] = useState(false);

  const filteredRepositoryOptions = useMemo(() => {
    const query = repoQuery.trim().toLowerCase();
    if (!query) return repositoryOptions;
    return repositoryOptions.filter((repo) => {
      const normalizedName = repo.fullName.toLowerCase();
      const normalizedSource = repo.source.label.toLowerCase();
      return normalizedName.includes(query) || normalizedSource.includes(query);
    });
  }, [repoQuery, repositoryOptions]);

  const groupedRepositories = useMemo(() => {
    const groups = new Map<
      string,
      { key: string; heading: string; options: PortalScmRepositoryOption[] }
    >();

    filteredRepositoryOptions.forEach((option) => {
      const existingGroup = groups.get(option.source.key);
      if (existingGroup) {
        existingGroup.options.push(option);
        return;
      }
      groups.set(option.source.key, {
        key: option.source.key,
        heading: option.source.label,
        options: [option]
      });
    });

    return Array.from(groups.values());
  }, [filteredRepositoryOptions]);

  return (
    <Popover
      open={repoPickerOpen}
      onOpenChange={(open) => {
        setRepoPickerOpen(open);
        if (!open) setRepoQuery('');
        setRepoListHovered(false);
      }}
    >
      <PopoverTrigger asChild>
        <PromptInputButton
          aria-expanded={repoPickerOpen}
          aria-label="选择仓库"
          className="max-w-104 justify-between text-muted-foreground hover:text-foreground"
          role="combobox"
          type="button"
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <FolderGit2 className="size-4 shrink-0" />
            <span className="truncate">
              {selectedRepo ||
                (isRepositoryLoading ? '加载仓库中...' : '选择存储库')}
            </span>
          </span>
          <ChevronsUpDown className="size-4 opacity-60" />
        </PromptInputButton>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-70 p-0">
        <Command>
          <CommandInput
            placeholder="搜索仓库..."
            value={repoQuery}
            onValueChange={setRepoQuery}
          />
          <CommandList onMouseLeave={() => setRepoListHovered(false)}>
            <CommandEmpty>{repositoryEmptyMessage}</CommandEmpty>
            {groupedRepositories.map((group) => (
              <CommandGroup key={group.key} heading={group.heading}>
                {group.options.map((repo) => (
                  <CommandItem
                    className={cn(
                      !repoListHovered &&
                        'data-selected:bg-transparent data-selected:text-foreground',
                      selectedRepoKey === repo.key && 'font-medium'
                    )}
                    data-checked={selectedRepoKey === repo.key}
                    key={repo.key}
                    value={`${repo.fullName} ${repo.source.label}`}
                    onMouseMove={() => setRepoListHovered(true)}
                    onSelect={() => {
                      onSelectRepoKey(repo.key);
                      setRepoPickerOpen(false);
                      setRepoQuery('');
                      setRepoListHovered(false);
                    }}
                  >
                    <div className="min-w-0">
                      <p className="truncate">{repo.fullName}</p>
                      <p className="text-muted-foreground text-xs">
                        {repo.source.label}
                      </p>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
          <div className="border-t p-2">
            <Button
              className="w-full justify-start"
              size="sm"
              type="button"
              variant="outline"
              onClick={() => {
                setRepoPickerOpen(false);
                setRepoQuery('');
                setRepoListHovered(false);
                onOpenScmAuthDialog();
              }}
            >
              <Settings />
              绑定 GitHub / GitLab 授权
            </Button>
            <Button
              className="mt-2 w-full justify-start"
              size="sm"
              type="button"
              variant="ghost"
              onClick={onRefreshRepositories}
            >
              刷新仓库列表
            </Button>
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
