import { useMemo, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { AppLogo } from '@/components/app-logo';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { getAuthErrorMessage, useAuth } from '@/provider/auth';

type LoginRouteState = {
  from?: string;
};

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isLoggingIn } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authMethod, setAuthMethod] = useState<'local' | 'ldap'>('local');

  const redirectTo = useMemo(() => {
    const state = location.state as LoginRouteState | null;
    if (state?.from && state.from.startsWith('/')) return state.from;
    return '/';
  }, [location.state]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedUsername = username.trim();
    const trimmedPassword = password.trim();

    if (!trimmedUsername || !trimmedPassword) {
      toast.error('请输入用户名和密码');
      return;
    }

    try {
      await login({
        username: trimmedUsername,
        password: trimmedPassword,
        auth_method: authMethod
      });
      toast.success('登录成功');
      navigate(redirectTo, { replace: true });
    } catch (error) {
      toast.error(getAuthErrorMessage(error, '登录失败，请稍后重试'));
    }
  };

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/20 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-5">
          <div className="flex items-center justify-center">
            <AppLogo />
          </div>
          <CardTitle className="text-center text-2xl">登录 sandbox-agent</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label>认证方式</Label>
              <RadioGroup
                value={authMethod}
                onValueChange={(value) => setAuthMethod((value as 'local' | 'ldap') || 'local')}
                className="grid grid-cols-2 gap-2"
              >
                <label className="border-input flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm">
                  <RadioGroupItem id="auth-local" value="local" />
                  <span>账号密码</span>
                </label>
                <label className="border-input flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm">
                  <RadioGroupItem id="auth-ldap" value="ldap" />
                  <span>LDAP</span>
                </label>
              </RadioGroup>
            </div>
            <div className="space-y-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                autoComplete={authMethod === 'ldap' ? 'off' : 'username'}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder={authMethod === 'ldap' ? '请输入 LDAP 用户名' : '请输入用户名'}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
              />
            </div>
            <Button className="w-full cursor-pointer" type="submit" disabled={isLoggingIn}>
              {isLoggingIn ? '登录中...' : '登录'}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            还没有账号？{' '}
            <Link
              to="/register"
              state={location.state}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              去注册
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
