import { AppLogo } from '@/components/app-logo';
import { ThemeModeMenu } from '@/components/theme-mode-menu';
import { Button } from '@/components/ui/button';

type PortalHeaderProps = {
  onLogoClick: () => void;
  onSettingsClick: () => void;
  onLogout: () => void;
};

export function PortalHeader({
  onLogoClick,
  onSettingsClick,
  onLogout
}: PortalHeaderProps) {
  return (
    <header>
      <div className="flex w-full items-center justify-between py-3 text-sm text-muted-foreground">
        <AppLogo onClick={() => onLogoClick()} className="cursor-pointer" />
        <div className="flex items-center gap-2 sm:gap-5">
          <ThemeModeMenu />
          <Button type="button" variant="ghost" size="sm" onClick={onSettingsClick}>
            设置
          </Button>
          <Button type="button" variant="ghost" size="sm">
            文档
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onLogout}>
            退出登录
          </Button>
        </div>
      </div>
    </header>
  );
}
