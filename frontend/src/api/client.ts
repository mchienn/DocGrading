import createClient from 'openapi-fetch';
import type { paths } from './schema';

export const AUTH_EXPIRED_EVENT = 'docgrading:auth-expired';
export const authChannel = new BroadcastChannel('docgrading:auth-changed');

const CSRF_COOKIE_NAMES = ['__Host-csrf_token', 'csrf_token'];
const MUTATION_METHODS: Record<string, true> = {
  POST: true,
  PUT: true,
  PATCH: true,
  DELETE: true,
};

function csrfToken(): string | undefined {
  const cookies = document.cookie.split('; ');
  for (const name of CSRF_COOKIE_NAMES) {
    const prefix = `${name}=`;
    const cookie = cookies.find((item) => item.startsWith(prefix));
    if (cookie) return cookie.slice(prefix.length);
  }
}

function csrfFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = new Request(input, init);
  if (!MUTATION_METHODS[request.method.toUpperCase()]) return fetch(request);
  const token = csrfToken();
  if (!token) return fetch(request);
  const headers = new Headers(request.headers);
  headers.set('X-CSRF-Token', token);
  return fetch(new Request(request, { headers }));
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const api = createClient<paths>({
  baseUrl: '',
  credentials: 'include',
  fetch: csrfFetch,
});

type ApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

function errorMessage(error: unknown, status: number): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = error.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          item && typeof item === 'object' && 'msg' in item
            ? String(item.msg)
            : null,
        )
        .filter(Boolean);
      if (messages.length) return messages.join('. ');
    }
  }
  return `Request failed (${status})`;
}
export function broadcastAuthChange(): void {
  authChannel.postMessage(null);
}

function notifyAuthExpired(): void {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  broadcastAuthChange();
}

export async function apiData<T>(request: Promise<ApiResult<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok || data === undefined) {
    if (response.status === 401 && !response.url.endsWith('/auth/login')) {
      notifyAuthExpired();
    }
    throw new ApiError(errorMessage(error, response.status), response.status, error);
  }
  return data;
}

export async function apiVoid(request: Promise<ApiResult<unknown>>): Promise<void> {
  const { error, response } = await request;
  if (!response.ok) {
    if (response.status === 401) notifyAuthExpired();
    throw new ApiError(errorMessage(error, response.status), response.status, error);
  }
}

export function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected request error';
}
