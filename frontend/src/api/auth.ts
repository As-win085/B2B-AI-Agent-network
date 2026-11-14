import { apiRequest } from "./client";
import type {
  AuthSession,
  CurrentSession,
  LoginInput,
  LogoutResult,
  Organization,
  RegisterInput,
  SwitchOrganizationResult,
} from "../types/auth";

export function register(input: RegisterInput): Promise<AuthSession> {
  return apiRequest<AuthSession>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
    skipAuth: true,
    allowRefresh: false,
  });
}

export function login(input: LoginInput): Promise<AuthSession> {
  return apiRequest<AuthSession>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
    skipAuth: true,
    allowRefresh: false,
  });
}

export function refreshAuthSession(refreshToken: string): Promise<AuthSession> {
  return apiRequest<AuthSession>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
    skipAuth: true,
    allowRefresh: false,
  });
}

export function logout(refreshToken: string): Promise<LogoutResult> {
  return apiRequest<LogoutResult>("/api/v1/auth/logout", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
    skipAuth: true,
    allowRefresh: false,
  });
}

export function getMe(): Promise<CurrentSession> {
  return apiRequest<CurrentSession>("/api/v1/auth/me", { method: "GET" });
}

export function listOrganizations(): Promise<Organization[]> {
  return apiRequest<Organization[]>("/api/v1/organizations", { method: "GET" });
}

export function switchOrganization(organizationId: string): Promise<SwitchOrganizationResult> {
  return apiRequest<SwitchOrganizationResult>("/api/v1/organizations/switch", {
    method: "POST",
    body: JSON.stringify({ organization_id: organizationId }),
  });
}
