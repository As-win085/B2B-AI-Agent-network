import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import {
  login as loginRequest,
  logout as logoutRequest,
  refreshAuthSession,
  register as registerRequest,
  switchOrganization as switchOrganizationRequest,
} from "../../api/auth";
import { configureAuth, setAccessToken } from "../../api/client";
import type {
  AuthSession,
  AuthUser,
  LoginInput,
  Organization,
  RegisterInput,
} from "../../types/auth";
import { AuthContext } from "./authContext";
import type { AuthContextValue } from "./authContext";
import {
  clearStoredRefreshToken,
  readStoredRefreshToken,
  writeStoredRefreshToken,
} from "./authStorage";

interface AuthState {
  status: AuthContextValue["status"];
  user: AuthUser | null;
  organization: Organization | null;
  organizations: Organization[];
}

const ANONYMOUS: AuthState = {
  status: "anonymous",
  user: null,
  organization: null,
  organizations: [],
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ ...ANONYMOUS, status: "loading" });

  const applySession = useCallback((session: AuthSession) => {
    setAccessToken(session.access_token);
    writeStoredRefreshToken(session.refresh_token);
    setState({
      status: "authenticated",
      user: session.user,
      organization: session.organization ?? null,
      organizations: session.organizations,
    });
  }, []);

  const clearSession = useCallback(() => {
    clearStoredRefreshToken();
    setAccessToken(null);
    setState(ANONYMOUS);
  }, []);

  // Restore the session on reload using the stored refresh token.
  useEffect(() => {
    const stored = readStoredRefreshToken();
    if (!stored) {
      setState(ANONYMOUS);
      return;
    }

    let cancelled = false;
    refreshAuthSession(stored)
      .then((session) => {
        if (!cancelled) {
          applySession(session);
        }
      })
      .catch(() => {
        if (!cancelled) {
          clearSession();
        }
      });

    return () => {
      cancelled = true;
    };
  }, [applySession, clearSession]);

  // Wire the API client to this provider so transient 401s rotate once.
  useEffect(() => {
    configureAuth({
      refreshAccessToken: async () => {
        const stored = readStoredRefreshToken();
        if (!stored) {
          throw new Error("No refresh token is stored.");
        }
        const session = await refreshAuthSession(stored);
        applySession(session);
        return session.access_token;
      },
      onSessionExpired: clearSession,
    });

    return () => configureAuth(null);
  }, [applySession, clearSession]);

  const login = useCallback(
    async (input: LoginInput) => {
      const session = await loginRequest(input);
      applySession(session);
    },
    [applySession],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      const session = await registerRequest(input);
      applySession(session);
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    const stored = readStoredRefreshToken();
    try {
      if (stored) {
        await logoutRequest(stored);
      }
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const switchOrganization = useCallback(async (organizationId: string) => {
    const result = await switchOrganizationRequest(organizationId);
    setState((current) =>
      current.status === "authenticated"
        ? { ...current, organization: result.organization }
        : current,
    );
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status: state.status,
      user: state.user,
      organization: state.organization,
      organizations: state.organizations,
      login,
      register,
      logout,
      switchOrganization,
    }),
    [state, login, register, logout, switchOrganization],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
