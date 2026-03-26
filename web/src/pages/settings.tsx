import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { PortalHeader } from '@/business/portal/portal-header';
import { CodeReviewSettingsSection } from '@/business/portal/code-review-settings-section';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAuth } from '@/provider/auth';

type SettingsTabValue = 'code-review';

const resolveSettingsTab = (value: string | null): SettingsTabValue =>
  value === 'code-review' ? value : 'code-review';

export function SettingsPage() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = useMemo(
    () => resolveSettingsTab(searchParams.get('tab')),
    [searchParams]
  );

  const handleTabChange = (value: string) => {
    setSearchParams({ tab: resolveSettingsTab(value) });
  };

  return (
    <main className="h-svh overflow-hidden bg-background">
      <div className="relative flex h-full flex-col px-4 md:px-8">
        <div className="z-10 shrink-0 space-y-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <PortalHeader
            onLogoClick={() => navigate('/')}
            onSettingsClick={() => navigate('/settings?tab=code-review')}
            onLogout={() => logout()}
            showSettingsButton={false}
          />
        </div>

        <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-6 overflow-hidden py-4">
          <section className="shrink-0 space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              设置
            </h1>
            <p className="text-sm text-muted-foreground">
              当前仅保留实际需要的代码审查配置入口。
            </p>
          </section>

          <Tabs
            orientation="vertical"
            value={currentTab}
            onValueChange={handleTabChange}
            className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row"
          >
            <div className="shrink-0 md:w-44">
              <div className="shrink-0">
                <TabsList>
                  <TabsTrigger value="code-review">代码审查</TabsTrigger>
                </TabsList>
              </div>
            </div>

            <TabsContent value="code-review" className="min-h-0 flex-1 overflow-auto">
              <CodeReviewSettingsSection />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </main>
  );
}
