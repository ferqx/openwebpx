import { useMemo, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { AppLogo } from '@/components/app-logo';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { getAuthErrorMessage, useAuth } from '@/provider/auth';

type RegisterRouteState = {
  from?: string;
};

export function RegisterPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { register, isRegistering } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const redirectTo = useMemo(() => {
    const state = location.state as RegisterRouteState | null;
    if (state?.from && state.from.startsWith('/')) return state.from;
    return '/';
  }, [location.state]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedUsername = username.trim();
    const trimmedPassword = password.trim();
    const trimmedConfirmPassword = confirmPassword.trim();

    if (!trimmedUsername || !trimmedPassword || !trimmedConfirmPassword) {
      toast.error('请完整填写注册信息');
      return;
    }
    if (trimmedPassword.length < 6) {
      toast.error('密码长度至少 6 位');
      return;
    }
    if (trimmedPassword !== trimmedConfirmPassword) {
      toast.error('两次输入的密码不一致');
      return;
    }

    try {
      await register({ username: trimmedUsername, password: trimmedPassword });
      toast.success('注册成功，已自动登录');
      navigate(redirectTo, { replace: true });
    } catch (error) {
      toast.error(getAuthErrorMessage(error, '注册失败，请稍后重试'));
    }
  };

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/20 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-5">
          <div className="flex items-center justify-center">
            <AppLogo />
          </div>
          <CardTitle className="text-center text-2xl">注册 OpenWebPx 账号</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入用户名"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码（至少 6 位）"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm-password">确认密码</Label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="请再次输入密码"
              />
            </div>
            <Button className="w-full cursor-pointer" type="submit" disabled={isRegistering}>
              {isRegistering ? '注册中...' : '注册'}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            已有账号？{' '}
            <Link
              to="/login"
              state={location.state}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              去登录
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
