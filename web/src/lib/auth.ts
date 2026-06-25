export type AuthUser = {
  identity: string;
  display_name?: string;
  is_authenticated?: boolean;
  permissions?: string[];
  role?: string;
  team_id?: string;
  email?: string;
};

export type LoginResponse = {
  access_token: string;
  token_type?: string;
  user: AuthUser;
};

const AUTH_TOKEN_KEY = 'sandbox-agent:auth-token';

export const getStoredAuthToken = () => {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(AUTH_TOKEN_KEY) ?? '';
};

export const setStoredAuthToken = (token: string) => {
  if (typeof window === 'undefined') return;
  const trimmed = token.trim();
  if (!trimmed) {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
    return;
  }
  window.localStorage.setItem(AUTH_TOKEN_KEY, trimmed);
};

export const clearStoredAuthToken = () => {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
};

const toHeaders = (headers?: HeadersInit) => {
  return new Headers(headers ?? {});
};

export const withAuthHeaders = (init?: RequestInit): RequestInit => {
  const headers = toHeaders(init?.headers);
  const token = getStoredAuthToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  return {
    ...init,
    headers
  };
};

export const authFetch = async (input: RequestInfo | URL, init?: RequestInit) =>
  fetch(input, withAuthHeaders(init));
