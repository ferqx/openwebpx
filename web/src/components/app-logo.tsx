import { cn } from '@/lib/utils';

type AppLogoProps = {
  className?: string;
};

export function AppLogo({
  className,
  onClick
}: AppLogoProps & { onClick?: () => void }) {
  return (
    <span
      className={cn('flex items-center gap-2', className)}
      onClick={onClick}
    >
      <span className="bg-foreground text-background flex size-6 items-center justify-center rounded-md text-[11px] font-semibold">
        OW
      </span>
      <span className="font-semibold tracking-tight text-foreground">
        OpenWebPX
      </span>
    </span>
  );
}
