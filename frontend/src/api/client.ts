import type { ApiEnvelope, ApiErrorBody } from "../types/api";
import type { HealthResponse } from "../types/health";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: string,
    public readonly requestId?: string,
    public readonly details?: ApiErrorBody["error"]["details"],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface AuthHandlers {
  /**
   * Rotate the refresh token and return a fresh access token. The handler is
   * single-flighted by ``apiRequest`` so concurrent 401s trigger one refresh.
   */
  refreshAccessToken: () => Promise<string>;
  /** Called when a session can no longer be refreshed. */
  onSessionExpired: () => void;
}

export interface ApiRequestInit extends RequestInit {
  /** Do not attach the access token (used by login/register/refresh). */
  skipAuth?: boolean;
  /** Do not attempt a token refresh after a 401. */
  allowRefresh?: boolean;
  /** Return the complete success envelope when pagination metadata is needed. */
  includeMeta?: boolean;
}

let accessToken: string | null = null;
let authHandlers: AuthHandlers | null = null;
let refreshInFlight: Promise<string | null> | null = null;

/** Replace the in-memory access token (never persisted to storage). */
export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Register the auth provider callbacks used for refresh and logout handling. */
export function configureAuth(handlers: AuthHandlers | null): void {
  authHandlers = handlers;
  if (!handlers) {
    accessToken = null;
    refreshInFlight = null;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | undefined;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    body = undefined;
  }

  const error = body?.error;
  return new ApiError(
    error?.message ?? `Request failed with status ${response.status}`,
    response.status,
    error?.code,
    error?.request_id ?? undefined,
    error?.details,
  );
}

function refreshAccessToken(): Promise<string | null> {
  if (!authHandlers) {
    return Promise.resolve(null);
  }
  if (!refreshInFlight) {
    refreshInFlight = authHandlers
      .refreshAccessToken()
      .catch(() => {
        authHandlers?.onSessionExpired();
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function apiRequest<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const { skipAuth = false, allowRefresh = true, includeMeta = false, ...requestInit } = init;

  const headers = new Headers(requestInit.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (requestInit.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = skipAuth ? null : accessToken;
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const url = `${API_BASE_URL}${path}`;
  let response = await fetch(url, { ...requestInit, headers });

  if (response.status === 401 && allowRefresh && !skipAuth && authHandlers) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      headers.set("Authorization", `Bearer ${refreshed}`);
      response = await fetch(url, { ...requestInit, headers });
    }
  }

  if (!response.ok) {
    const error = await toApiError(response);
    if (response.status === 401 && !skipAuth) {
      authHandlers?.onSessionExpired();
    }
    throw error;
  }

  const body = (await response.json()) as ApiEnvelope<T>;
  return (includeMeta ? body : body.data) as T;
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/api/v1/health", {
    method: "GET",
    signal,
    skipAuth: true,
    allowRefresh: false,
  });
}
