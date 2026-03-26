import { AppSidebar } from '@/components/app-sidebar';
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger
} from '@/components/ui/sidebar';
import { StreamProvider } from '@/provider/stream';
import { ThreadProvider } from '@/provider/thread';
import { Outlet, useLocation } from 'react-router-dom';

export default function Dashboard() {
  const location = useLocation();
  const isPortalPage =
    location.pathname === '/' ||
    location.pathname.startsWith('/tasks/') ||
    location.pathname.startsWith('/reviews/');

  return (
    <ThreadProvider>
      <StreamProvider>
        <SidebarProvider className="h-svh">
          {!isPortalPage && <AppSidebar />}
          <SidebarInset>
            {!isPortalPage && (
              <SidebarTrigger
                variant={'outline'}
                className="absolute left-3 top-3"
              />
            )}
            <Outlet />
          </SidebarInset>
        </SidebarProvider>
      </StreamProvider>
    </ThreadProvider>
  );
}
