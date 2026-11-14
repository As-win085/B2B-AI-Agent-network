import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const healthPayload = {
  status: "ok",
  service: "Asama.ai API",
  version: "0.1.0",
  environment: "local",
  timestamp: "2026-11-14T07:00:00Z",
};
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders the workspace and loads API health", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ data: healthPayload }),
      }),
    );

    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText("Asama.ai foundation is running")).toBeInTheDocument();
    expect(await screen.findByText("Asama.ai API")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Operational");
  });

  it("renders the not-found page for unknown routes", () => {
    render(
      <MemoryRouter initialEntries={["/missing"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});
