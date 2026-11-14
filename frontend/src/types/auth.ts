export type OrganizationRole = "owner" | "admin" | "member";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  role: OrganizationRole;
}

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
  organization?: Organization | null;
  organizations: Organization[];
}

export interface CurrentSession {
  user: AuthUser;
  organization?: Organization | null;
  organizations: Organization[];
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput {
  email: string;
  password: string;
  full_name?: string;
  organization_name: string;
  organization_slug?: string;
}

export interface SwitchOrganizationResult {
  organization: Organization;
}

export interface LogoutResult {
  logged_out: boolean;
}
