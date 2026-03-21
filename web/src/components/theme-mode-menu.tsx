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
import { Button } from '@/components/ui/button';

type ThemeMode = 'light' | 'dark' | 'system';

const getThemeLabel = (theme: ThemeMode) => {
  if (theme === 'light') return '亮色';
  if (theme === 'dark') return '暗色';
  return '跟随系统';
};

const ThemeIcon = ({ theme }: { theme: ThemeMode }) => {
  if (theme === 'light') return <Sun className="size-4" />;
  if (theme === 'dark') return <Moon className="size-4" />;
  return <Monitor className="size-4" />;
};

type ThemeModeMenuProps = {
  buttonClassName?: string;
};

export function ThemeModeMenu({ buttonClassName }: ThemeModeMenuProps) {
  const { theme, setTheme } = useTheme();
  const currentTheme: ThemeMode =
    theme === 'light' || theme === 'dark' || theme === 'system'
      ? theme
      : 'system';

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className={buttonClassName}>
          <ThemeIcon theme={currentTheme} />
          {getThemeLabel(currentTheme)}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8}>
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
  );
}
