import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem
} from '@/components/ui/sidebar';

type ThemeMode = 'light' | 'dark' | 'system';

function getThemeLabel(theme: ThemeMode) {
  if (theme === 'light') return '亮色';
  if (theme === 'dark') return '暗色';
  return '跟随系统';
}

function ThemeIcon({ theme }: { theme: ThemeMode }) {
  if (theme === 'light') return <Sun />;
  if (theme === 'dark') return <Moon />;
  return <Monitor />;
}

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();
  const currentTheme: ThemeMode =
    theme === 'light' || theme === 'dark' || theme === 'system'
      ? theme
      : 'system';

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton tooltip="主题">
              <ThemeIcon theme={currentTheme} />
              <span>{getThemeLabel(currentTheme)}</span>
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="right" align="end" sideOffset={6}>
            <DropdownMenuLabel>主题模式</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuRadioGroup
              value={currentTheme}
              onValueChange={(value) => setTheme(value as ThemeMode)}
            >
              <DropdownMenuRadioItem value="light">
                <Sun />
                亮色
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark">
                <Moon />
                暗色
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system">
                <Monitor />
                跟随系统
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
