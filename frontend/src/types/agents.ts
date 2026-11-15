export type AgentStatus = "active" | "suspended" | "deactivated";

export interface Agent {
  id: string;
  organization_id: string;
  company_name: string;
  industry_category: string | null;
  interest_manifesto: string | null;
  webhook_url: string | null;
  webhook_configured: boolean;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
}

export interface AgentCredential {
  id: string;
  agent_id: string;
  label: string | null;
  credential_prefix: string;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface IssuedCredential {
  credential: AgentCredential;
  secret: string;
}
