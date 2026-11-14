/**
 * Refresh-token persistence.
 *
 * The access token is kept in memory only. The refresh token lives in
 * ``localStorage`` so a page reload can restore the session. This is a
 * deliberate trade-off: it is readable by JavaScript, so an XSS bug could steal
 * it. Moving to an httpOnly cookie with CSRF protection is the planned
 * hardening step and is tracked as a follow-up to ASAMA-103.
 */
const REFRESH_TOKEN_KEY = "asama.refresh_token";

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readStoredRefreshToken(): string | null {
  return storage()?.getItem(REFRESH_TOKEN_KEY) ?? null;
}

export function writeStoredRefreshToken(token: string): void {
  storage()?.setItem(REFRESH_TOKEN_KEY, token);
}

export function clearStoredRefreshToken(): void {
  storage()?.removeItem(REFRESH_TOKEN_KEY);
}
