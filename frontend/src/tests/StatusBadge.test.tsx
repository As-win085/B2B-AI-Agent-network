import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "../components/StatusBadge";

describe("StatusBadge", () => {
  it("renders the operational label", () => {
    render(<StatusBadge status="ok" />);
    expect(screen.getByRole("status")).toHaveTextContent("Operational");
  });

  it("renders the unreachable label", () => {
    render(<StatusBadge status="error" />);
    expect(screen.getByRole("status")).toHaveTextContent("Unreachable");
  });
});
