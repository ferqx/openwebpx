import * as React from 'react';
import {
  AudioWaveform,
  Command,
  BotMessageSquare,
  GalleryVerticalEnd,
  PencilRuler,
  Plus
} from 'lucide-react';
import { NavUser } from '@/components/nav-user';
import { TeamSwitcher } from '@/components/team-switcher';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRail,
  SidebarMenu,
  SidebarMenuItem,
  SidebarGroup,
  SidebarGroupLabel
} from '@/components/ui/sidebar';
import { useNavigate } from 'react-router-dom';
import { NavBuildApps } from './nav-build-apps';
import { Button } from './ui/button';
import { ThemeSwitcher } from './theme-switcher';
import { useAuth } from '@/provider/auth';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from './ui/dropdown-menu';

// This is sample data.
const data = {
  user: {
    name: 'shadcn',
    email: 'm@example.com',
    avatar: '/avatars/shadcn.jpg'
  },
  teams: [
    {
      name: 'Acme Inc',
      logo: GalleryVerticalEnd,
      plan: 'Enterprise'
    },
    {
      name: 'Acme Corp.',
      logo: AudioWaveform,
      plan: 'Startup'
    },
    {
      name: 'Evil Corp.',
      logo: Command,
      plan: 'Free'
    }
  ],
  navMain: [
    {
      title: '聊天',
      url: '#',
      icon: BotMessageSquare,
      isActive: true,
      items: [
        {
          title: 'History',
          url: '#'
        },
        {
          title: 'Starred',
          url: '#'
        },
        {
          title: 'Settings',
          url: '#'
        }
      ]
    },
    {
      title: '应用',
      url: '#',
      icon: PencilRuler,
      items: [
        {
          title: 'Genesis',
          url: '#'
        },
        {
          title: 'Explorer',
          url: '#'
        },
        {
          title: 'Quantum',
          url: '#'
        }
      ]
    }
  ]
};

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const sidebarUser = {
    name: user?.display_name?.trim() || user?.identity || 'User',
    email: user?.email?.trim() || '未设置邮箱',
    avatar: '/avatars/shadcn.jpg'
  };

  const handleLogout = () => {
    void logout().finally(() => {
      navigate('/login', { replace: true });
    });
  };

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <TeamSwitcher teams={data.teams} />
        <SidebarMenu>
          <SidebarMenuItem></SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>
            <span>Platform</span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant={'ghost'}
                  size={'icon'}
                  className="ml-auto cursor-pointer"
                >
                  <Plus />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-46">
                <DropdownMenuLabel>开始</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  {/* <DropdownMenuItem onSelect={() => navigate('/chat/new_chat')}>
                    <BotMessageSquare />
                    <span>聊天</span>
                  </DropdownMenuItem> */}
                  <DropdownMenuItem onSelect={() => navigate('/')}>
                    <PencilRuler />
                    <span>构建</span>
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarGroupLabel>
          <SidebarMenu>
            {/* <NavSessions /> */}
            <NavBuildApps />
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <ThemeSwitcher />
        <NavUser user={sidebarUser} onLogout={handleLogout} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
