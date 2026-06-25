import { useEffect, useMemo } from 'react';
import {
  clearScmOAuthSessionState,
  completeScmOAuthCallback,
  getScmOAuthSessionState,
  persistScmOAuthResult
} from '@/lib/scm';

const SCM_CALLBACK_STATUS_KEY_PREFIX = 'sandbox-agent:scm-oauth-callback';

export function ScmOauthCallbackPage() {
  const search = useMemo(
    () => new URLSearchParams(window.location.search),
    []
  );
  const oauthError = useMemo(() => search.get('error'), [search]);
  const oauthErrorDescription = useMemo(
    () => search.get('error_description') || 'OAuth 授权失败',
    [search]
  );
  const callbackStatusStorageKey = useMemo(() => {
    const state = search.get('state')?.trim() ?? '';
    const code = search.get('code')?.trim() ?? '';
    if (!state && !code) return '';
    return `${SCM_CALLBACK_STATUS_KEY_PREFIX}:${state}:${code}`;
  }, [search]);

  useEffect(() => {
    const sessionState = getScmOAuthSessionState();
    const redirectTo =
      sessionState?.returnTo && sessionState.returnTo.startsWith('/')
        ? sessionState.returnTo
        : '/';
    const provider = sessionState?.provider ?? 'github';

    const finish = (ok: boolean, error?: string) => {
      persistScmOAuthResult({
        ok,
        provider,
        error,
        gitlabBaseUrl: sessionState?.gitlabBaseUrl
      });
      clearScmOAuthSessionState();
      window.location.replace(redirectTo);
    };

    const getCallbackStatus = () => {
      if (!callbackStatusStorageKey) return null;
      return window.sessionStorage.getItem(callbackStatusStorageKey);
    };

    const setCallbackStatus = (status: 'processing' | 'done') => {
      if (!callbackStatusStorageKey) return;
      window.sessionStorage.setItem(callbackStatusStorageKey, status);
    };

    const clearCallbackStatus = () => {
      if (!callbackStatusStorageKey) return;
      window.sessionStorage.removeItem(callbackStatusStorageKey);
    };

    if (oauthError) {
      clearCallbackStatus();
      finish(false, oauthErrorDescription);
      return;
    }

    const existingStatus = getCallbackStatus();
    if (existingStatus === 'processing') {
      return;
    }
    if (existingStatus === 'done') {
      finish(true);
      return;
    }
    setCallbackStatus('processing');

    completeScmOAuthCallback(search)
      .then((result) => {
        if (!result.ok) {
          clearCallbackStatus();
          finish(false, result.error || 'OAuth 授权失败');
          return;
        }
        setCallbackStatus('done');
        finish(true);
      })
      .catch((error) => {
        clearCallbackStatus();
        const detail =
          error instanceof Error ? error.message : 'OAuth 回调处理失败';
        finish(false, detail);
      });
  }, [callbackStatusStorageKey, oauthError, oauthErrorDescription, search]);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-6">
      <div className="max-w-md rounded-xl border bg-card p-6 text-center">
        <p className="text-base font-medium">
          {oauthError ? '授权失败' : '正在处理授权'}
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          {oauthError
            ? oauthErrorDescription
            : '请稍候，页面将自动返回并刷新仓库列表。'}
        </p>
      </div>
    </main>
  );
}
