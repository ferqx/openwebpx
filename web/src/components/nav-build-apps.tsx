import {
  ChevronRight,
  Trash,
  MoreVertical,
  PencilRulerIcon
} from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger
} from '@/components/ui/collapsible';
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem
} from '@/components/ui/sidebar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useThreads } from '@/provider/thread';

export function NavBuildApps() {
  const navigate = useNavigate();
  const { threads, getThreads, currentThread, deleteThread } = useThreads();

  useEffect(() => {
    getThreads();
  }, [getThreads]);

  const openSession = (sessionId: string) => {
    navigate(`/tasks/${sessionId}`);
  };

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    await deleteThread(sessionId);
    if (currentThread?.thread_id === sessionId) {
      navigate('/');
    }
  };

  return (
    <Collapsible asChild defaultOpen={true} className="group/collapsible">
      <SidebarMenuItem>
        <CollapsibleTrigger asChild>
          <SidebarMenuButton
            tooltip={'构建'}
            style={{ padding: 'calc(var(--spacing) * 2)' }}
          >
            <PencilRulerIcon />
            <span>构建</span>
            <ChevronRight className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
          </SidebarMenuButton>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <SidebarMenuSub className="border-0 m-0">
            {threads.map((session) => (
              <SidebarMenuSubItem className="group/sub" key={session.thread_id}>
                <SidebarMenuSubButton
                  isActive={currentThread?.thread_id === session.thread_id}
                  asChild
                  className="h-8"
                >
                  <div
                    onClick={() => openSession(session.thread_id!)}
                    className="cursor-pointer group-hover/sub:pr-8 has-data-[state=open]:pr-10"
                  >
                    <span className="truncate">
                      {(session.metadata?.name as string) || '未命名对话'}
                    </span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <SidebarMenuAction className="top-1 opacity-0 group-hover/sub:opacity-100 data-[state=open]:opacity-100 transition-opacity px-2">
                          <MoreVertical className="h-4 w-4 cursor-pointer" />
                        </SidebarMenuAction>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent side="right" align="start">
                        <DropdownMenuItem
                          className="text-destructive"
                          onClick={(e) => handleDelete(e, session.thread_id!)}
                        >
                          <Trash className="mr-2 h-4 w-4" />
                          <span>删除</span>
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </CollapsibleContent>
      </SidebarMenuItem>
    </Collapsible>
  );
}
