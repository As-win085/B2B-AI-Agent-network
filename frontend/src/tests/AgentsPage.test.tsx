import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentsPage } from "../pages/AgentsPage";

const mocks = vi.hoisted(() => ({ listAgents: vi.fn(), registerAgent: vi.fn() }));

vi.mock("../api/agents", () => ({
  configureWebhook: vi.fn(),
  issueCredential: vi.fn(),
  listAgents: mocks.listAgents,
  listCredentials: vi.fn().mockResolvedValue([]),
  registerAgent: mocks.registerAgent,
  revokeCredential: vi.fn(),
  setAgentStatus: vi.fn(),
  testWebhook: vi.fn(),
  updateAgent: vi.fn(),
}));

vi.mock("../features/auth/authContext", () => ({
  useAuth: () => ({ organization: { name: "Acme", role: "owner" } }),
}));

const agent = {
  id: "agent-1",
  organization_id: "org-1",
  company_name: "Acme Helper",
  industry_category: "Technology",
  interest_manifesto: "AI partnerships",
  webhook_url: null,
  webhook_configured: false,
  status: "active" as const,
  created_at: "2026-11-14T00:00:00Z",
  updated_at: "2026-11-14T00:00:00Z",
};

describe("AgentsPage", () => {
  beforeEach(() => {
    mocks.listAgents.mockReset().mockResolvedValue([agent]);
    mocks.registerAgent.mockReset().mockResolvedValue(agent);
  });

  it("lists organization agents and shows management controls", async () => {
    render(<AgentsPage />);
    expect(await screen.findByText("Acme Helper")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Register an agent" })).toBeInTheDocument();
  });

  it("submits the registration form", async () => {
    render(<AgentsPage />);
    await screen.findByText("Acme Helper");
    fireEvent.change(screen.getByLabelText("Company or agent name"), {
      target: { value: "New Bot" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register agent" }));
    await waitFor(() =>
      expect(mocks.registerAgent).toHaveBeenCalledWith({
        company_name: "New Bot",
        industry_category: undefined,
        interest_manifesto: undefined,
      }),
    );
  });
});
