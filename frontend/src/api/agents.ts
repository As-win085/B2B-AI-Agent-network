import { apiRequest } from "./client";
import type { Agent, AgentCredential, IssuedCredential } from "../types/agents";

export function getAuthenticatedAgent(key: string): Promise<Agent> {
  return apiRequest<Agent>("/api/v1/agents/me", {
    skipAuth: true,
    allowRefresh: false,
    headers: { Authorization: `Bearer ${key}` },
  });
}

export function listAgents(): Promise<Agent[]> {
  return apiRequest<Agent[]>("/api/v1/agents");
}

export function registerAgent(input: {
  company_name: string;
  industry_category?: string;
  interest_manifesto?: string;
}): Promise<Agent> {
  return apiRequest<Agent>("/api/v1/agents", { method: "POST", body: JSON.stringify(input) });
}

export function updateAgent(
  id: string,
  input: Partial<Pick<Agent, "company_name" | "industry_category" | "interest_manifesto">>,
): Promise<Agent> {
  return apiRequest<Agent>(`/api/v1/agents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function setAgentStatus(
  id: string,
  action: "suspend" | "reactivate" | "deactivate",
): Promise<Agent> {
  return apiRequest<Agent>(`/api/v1/agents/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export function listCredentials(id: string): Promise<AgentCredential[]> {
  return apiRequest<AgentCredential[]>(`/api/v1/agents/${id}/credentials`);
}

export function issueCredential(
  id: string,
  input: { label?: string; expires_in_days?: number; rotate?: boolean },
): Promise<IssuedCredential> {
  return apiRequest<IssuedCredential>(`/api/v1/agents/${id}/credentials`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function revokeCredential(agentId: string, credentialId: string): Promise<AgentCredential> {
  return apiRequest<AgentCredential>(`/api/v1/agents/${agentId}/credentials/${credentialId}`, {
    method: "DELETE",
  });
}

export function configureWebhook(
  id: string,
  input: { webhook_url: string; rotate_secret?: boolean },
): Promise<{ webhook_url: string; webhook_configured: boolean; signing_secret?: string }> {
  return apiRequest(`/api/v1/agents/${id}/webhook`, { method: "PUT", body: JSON.stringify(input) });
}

export function testWebhook(
  id: string,
): Promise<{ valid: boolean; delivery_attempted: boolean; url: string }> {
  return apiRequest(`/api/v1/agents/${id}/webhook/test`, { method: "POST" });
}
