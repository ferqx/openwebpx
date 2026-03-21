import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import {
  authFetch,
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
  type AuthUser,
  type LoginResponse
} from '@/lib/auth';
import { Spinner } from '@/components/ui/spinner';

type AuthContextValue = {
  user: AuthUser | null;
  token: string;
  isAuthenticated: boolean;
  isInitializing: boolean;
  isLoggingIn: boolean;
  isRegistering: boolean;
  login: (payload: {
    username: string;
    password: string;
    auth_method?: 'local' | 'ldap';
  }) => Promise<void>;
  register: (payload: {
    username: string;
    password: string;
    role?: 'admin' | 'premium' | 'developer' | 'reviewer' | 'free';
    team_id?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const AUTH_RETRY_DELAYS_MS = [300, 1000, 2000] as const;

class AuthResponseError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'AuthResponseError';
    this.status = status;
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const pickMessageFromRecord = (record: Record<string, unknown>) => {
  const direct = [record.message, record.error, record.detail].find(
    (item) => typeof item === 'string' && item.trim()
  );
  if (typeof direct === 'string') return direct.trim();

  if (Array.isArray(record.detail)) {
    for (const item of record.detail) {
      if (typeof item === 'string' && item.trim()) return item.trim();
      if (isRecord(item)) {
        const nested = [item.msg, item.message, item.detail].find(
          (entry) => typeof entry === 'string' && entry.trim()
        );
        if (typeof nested === 'string') return nested.trim();
      }
    }
  }

  return '';
};

const parseErrorMessage = async (response: Response) => {
  try {
    const data = (await response.json()) as unknown;
    if (isRecord(data)) {
      const message = pickMessageFromRecord(data);
      if (message) return message;
    }
  } catch {
    try {
      const text = (await response.text()).trim();
      if (text) return text;
    } catch {
      // noop
    }
  }
  return `请求失败（${response.status}）`;
};

export const getAuthErrorMessage = (
  error: unknown,
  fallback = '请求失败，请稍后重试'
) => {
  if (error instanceof Error) {
    const message = error.message.trim();
    if (!message) return fallback;
    if (message === 'Failed to fetch') {
      return '网络连接失败，请检查服务是否可用';
    }
    return message;
  }
  return fallback;
};

const fetchCurrentUser = async (): Promise<AuthUser> => {
  const response = await authFetch('/api/auth/me', { method: 'GET' });
  if (!response.ok) {
    throw new AuthResponseError(response.status, await parseErrorMessage(response));
  }
  return (await response.json()) as AuthUser;
};

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });

const LoadingScreen = () => {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background">
      <Spinner className="size-6" />
    </div>
  );
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState('');
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);

  const refreshUser = useCallback(async () => {
    try {
      const nextUser = await fetchCurrentUser();
      setUser(nextUser);
    } catch (error) {
      if (
        error instanceof AuthResponseError &&
        (error.status === 401 || error.status === 403)
      ) {
        clearStoredAuthToken();
        setToken('');
        setUser(null);
      }
      throw error;
    }
  }, []);

  useEffect(() => {
    let active = true;
    const run = async () => {
      const storedToken = getStoredAuthToken();
      setToken(storedToken);
      if (!storedToken) {
        if (active) setIsInitializing(false);
        return;
      }
      let shouldClearToken = false;

      for (let attempt = 0; attempt <= AUTH_RETRY_DELAYS_MS.length; attempt += 1) {
        try {
          const currentUser = await fetchCurrentUser();
          if (!active) return;
          setUser(currentUser);
          if (active) setIsInitializing(false);
          return;
        } catch (error) {
          if (error instanceof AuthResponseError) {
            if (error.status === 401 || error.status === 403) {
              shouldClearToken = true;
              break;
            }
            // 非鉴权错误（例如 5xx）走重试，不立即清 token
          } else {
            // 网络错误等也走重试，不立即清 token
          }

          if (attempt < AUTH_RETRY_DELAYS_MS.length) {
            await sleep(AUTH_RETRY_DELAYS_MS[attempt]);
            continue;
          }
        }
        break;
      }

      if (shouldClearToken) {
        clearStoredAuthToken();
        if (!active) return;
        setToken('');
      }
      if (!active) return;
      setUser(null);
      setIsInitializing(false);
    };
    run().catch(() => {
      if (!active) return;
      setIsInitializing(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(
    async ({
      username,
      password,
      auth_method
    }: {
      username: string;
      password: string;
      auth_method?: 'local' | 'ldap';
    }) => {
      setIsLoggingIn(true);
      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            username,
            password,
            ...(auth_method ? { auth_method } : {})
          })
        });
        if (!response.ok) {
          throw new Error(await parseErrorMessage(response));
        }
        const data = (await response.json()) as LoginResponse;
        if (!data.access_token) {
          throw new Error('登录响应缺少 access_token');
        }
        setStoredAuthToken(data.access_token);
        setToken(data.access_token);
        setUser(data.user);
      } finally {
        setIsLoggingIn(false);
      }
    },
    []
  );

  const register = useCallback(
    async (payload: {
      username: string;
      password: string;
      role?: 'admin' | 'premium' | 'developer' | 'reviewer' | 'free';
      team_id?: string;
    }) => {
      setIsRegistering(true);
      try {
        const response = await fetch('/api/auth/register', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });
        if (!response.ok) {
          throw new Error(await parseErrorMessage(response));
        }
        const data = (await response.json()) as LoginResponse;
        if (!data.access_token) {
          throw new Error('注册响应缺少 access_token');
        }
        setStoredAuthToken(data.access_token);
        setToken(data.access_token);
        setUser(data.user);
      } finally {
        setIsRegistering(false);
      }
    },
    []
  );

  const logout = useCallback(async () => {
    clearStoredAuthToken();
    setToken('');
    setUser(null);
    try {
      await authFetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      });
    } catch {
      // logout endpoint failure should not block local signout
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isAuthenticated: Boolean(token && user),
      isInitializing,
      isLoggingIn,
      isRegistering,
      login,
      register,
      logout,
      refreshUser
    }),
    [
      isInitializing,
      isLoggingIn,
      isRegistering,
      login,
      register,
      logout,
      refreshUser,
      token,
      user
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

type RedirectState = {
  from?: string;
};

export function RequireAuth() {
  const location = useLocation();
  const { isAuthenticated, isInitializing } = useAuth();

  if (isInitializing) {
    return <LoadingScreen />;
  }

  if (!isAuthenticated) {
    const redirectTarget = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/login" replace state={{ from: redirectTarget }} />;
  }

  return <Outlet />;
}

export function RedirectIfAuthenticated() {
  const location = useLocation();
  const { isAuthenticated, isInitializing } = useAuth();
  const state = location.state as RedirectState | null;

  if (isInitializing) {
    return <LoadingScreen />;
  }

  if (isAuthenticated) {
    const redirectTo = state?.from && state.from.startsWith('/') ? state.from : '/';
    return <Navigate to={redirectTo} replace />;
  }

  return <Outlet />;
}
