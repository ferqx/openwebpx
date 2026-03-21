import { useNavigate } from 'react-router-dom';
import { PortalHeader } from '@/business/portal/portal-header';
import { useAuth } from '@/provider/auth';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export function SettingsPage() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  return (
    <main className="h-full overflow-auto bg-background">
      <div className="relative px-4 pb-8 md:px-8 space-y-4">
        <PortalHeader
          onLogoClick={() => navigate('/')}
          onSettingsClick={() => navigate('/settings')}
          onLogout={() => logout()}
        />
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">
            设置
          </h1>
        </div>
        <Tabs
          defaultValue="profile"
          orientation="vertical"
          className="flex w-full flex-col gap-6 md:flex-row md:gap-10"
        >
          <TabsList className="h-auto w-full flex-row justify-start gap-1 overflow-x-auto bg-transparent p-0 md:w-48 md:flex-col md:overflow-visible">
            <TabsTrigger
              value="profile"
              className="w-auto justify-start px-3 py-2 data-[state=active]:bg-background data-[state=active]:shadow-sm md:w-full"
            >
              个人资料
            </TabsTrigger>
          </TabsList>

          <div className="flex-1 px-8">
            <TabsContent value="profile" className="mt-0">
              <Card>
                <CardHeader>
                  <CardTitle>个人资料</CardTitle>
                  <CardDescription>
                    管理您的公开信息和个人资料。
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-2">
                    <Label htmlFor="username">用户名</Label>
                    <Input id="username" defaultValue="chenchao" />
                  </div>
                  <div className="grid gap-2">
                    <Label htmlFor="email">邮箱</Label>
                    <Input id="email" defaultValue="chenchao@example.com" />
                  </div>
                  <Button>保存更改</Button>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="appearance" className="mt-0">
              <Card>
                <CardHeader>
                  <CardTitle>外观</CardTitle>
                  <CardDescription>自定义界面的外观和感觉。</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="text-sm text-muted-foreground">
                    外观设置功能正在开发中...
                  </div>
                </CardContent>
              </Card>
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </main>
  );
}
