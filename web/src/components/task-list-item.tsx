import {
  CheckCircle2,
  CircleStop,
  LoaderCircle,
  SquareDashed,
  Trash2
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { TaskStatus } from '@/lib/tasks';
import { cn } from '@/lib/utils';

type TaskListItemProps = {
  title: string;
  subtitle: string;
  status: TaskStatus;
  statusText: string;
  onClick?: () => void;
  onDelete?: () => void;
  onCancel?: () => void;
  cancelDisabled?: boolean;
};

const TASK_STATUS_STYLES: Record<
  TaskStatus,
  {
    icon: typeof LoaderCircle;
    className: string;
    iconClassName?: string;
  }
> = {
  completed: {
    icon: CheckCircle2,
    className: 'border-border bg-background text-foreground shadow-xs'
  },
  running: {
    icon: LoaderCircle,
    className:
      'border-transparent bg-secondary text-secondary-foreground shadow-xs',
    iconClassName: 'animate-spin'
  },
  starting: {
    icon: LoaderCircle,
    className:
      'border-transparent bg-muted text-muted-foreground shadow-xs',
    iconClassName: 'animate-spin'
  },
  stopped: {
    icon: SquareDashed,
    className:
      'border-border bg-muted/60 text-muted-foreground shadow-xs'
  }
};

export function TaskListItem({
  title,
  subtitle,
  status,
  statusText,
  onClick,
  onDelete,
  onCancel,
  cancelDisabled = false
}: TaskListItemProps) {
  const statusStyle = TASK_STATUS_STYLES[status];
  const StatusIcon = statusStyle.icon;

  return (
    <div
      className={cn(
        'group/task-item flex items-center justify-between gap-3 p-4',
        onClick && 'cursor-pointer transition-colors hover:bg-muted/80'
      )}
      onClick={onClick}
    >
      <div className="min-w-0 space-y-1">
        <p className={cn('truncate font-medium text-sm text-foreground')}>
          {title}
        </p>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Badge
          variant="outline"
          className={cn(
            'h-7 rounded-full px-2.5 text-[11px] font-medium tracking-[0.01em]',
            statusStyle.className
          )}
        >
          <StatusIcon className={cn('size-3.5', statusStyle.iconClassName)} />
          {statusText}
        </Badge>
        {onCancel && (
          <Button
            aria-label="取消执行"
            disabled={cancelDisabled}
            size="icon"
            type="button"
            variant="ghost"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onCancel();
            }}
          >
            <CircleStop className="size-4" />
          </Button>
        )}
        {onDelete && (
          <Button
            aria-label="删除任务"
            className="pointer-events-none opacity-0 transition-opacity group-hover/task-item:pointer-events-auto group-hover/task-item:opacity-100"
            size="icon"
            type="button"
            variant="ghost"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onDelete();
            }}
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}
