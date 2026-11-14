import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { login, logout, register } from "../api/auth";
import { App } from "../App";
import type { AuthSession } from "../types/auth";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    getHealth: vi.fn().mockResolvedValue({
      status: "ok",
      service: "Asama.ai API",
      version: "0.1.0",
      environment: "test",
      timestamp: "2026-11-14T07:00:00Z",
    }),
  };
});

vi.mock("../api/auth", () => ({
  login: vi.fn(),
  register: vi.fn(),
  refreshAuthSession: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
  listOrganizations: vi.fn(),
  switchOrganization: vi.fn(),
}));

const organization = {
  id: "11111111-1111-1111-1111-111111111111",
  name: "Acme",
  slug: "acme",
  is_active: true,
  role: "owner" as const,
};

const session: AuthSession = {
  access_token: "access-token",
  refresh_token: "refresh-token",
  token_type: "bearer",
  expires_in: 900,
  user: {
    id: "22222222-2222-2222-2222-222222222222",
    email: "owner@example.test",
    full_name: "Ada Owner",
    is_active: true,
    is_verified: false,
    created_at: "2026-11-14T07:00:00Z",
  },
  organization,
  organizations: [organization],
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

function fillLogin(email = "owner@example.test", password = "correct horse battery staple") {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /^sign in$/i }));
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("authentication flow", () => {
  it("signs in and shows the workspace overview", async () => {
    vi.mocked(login).mockResolvedValue(session);

    renderAt("/login");
    fillLogin();

    expect(await screen.findByText(/welcome back, ada owner/i)).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith({
      email: "owner@example.test",
      password: "correct horse battery staple",
    });
    expect(window.localStorage.getItem("asama.refresh_token")).toBe("refresh-token");
  });

  it("shows the API error message when credentials are rejected", async () => {
    vi.mocked(login).mockRejectedValue(new Error("Invalid email or password."));

    renderAt("/login");
    fillLogin();

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  });

  it("requires a valid password before registering", async () => {
    renderAt("/register");

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "new@example.test" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "short" } });
    fireEvent.change(screen.getByLabelText(/organization name/i), {
      target: { value: "New Co" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Password must be at least 12 characters long.",
    );
    expect(register).not.toHaveBeenCalled();
  });

  it("registers a new owner and opens the workspace", async () => {
    vi.mocked(register).mockResolvedValue(session);

    renderAt("/register");

    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: "Ada Owner" } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "owner@example.test" } });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "correct horse battery staple" },
    });
    fireEvent.change(screen.getByLabelText(/organization name/i), {
      target: { value: "Acme" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/welcome back, ada owner/i)).toBeInTheDocument();
    expect(register).toHaveBeenCalledWith({
      email: "owner@example.test",
      password: "correct horse battery staple",
      full_name: "Ada Owner",
      organization_name: "Acme",
    });
  });

  it("signs out and returns to the login page", async () => {
    vi.mocked(login).mockResolvedValue(session);
    vi.mocked(logout).mockResolvedValue({ logged_out: true });

    renderAt("/login");
    fillLogin();
    await screen.findByText(/welcome back, ada owner/i);

    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));

    expect(await screen.findByRole("heading", { name: /sign in to asama/i })).toBeInTheDocument();
    expect(logout).toHaveBeenCalledWith("refresh-token");
    expect(window.localStorage.getItem("asama.refresh_token")).toBeNull();
  });
});
