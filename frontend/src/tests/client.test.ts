import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHealth } from "../api/client";

const healthPayload = {
  status: "ok",
  service: "Asama.ai API",
  version: "0.2.0",
  environment: "test",
  timestamp: "2026-11-14T07:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("unwraps the canonical success envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ data: healthPayload }),
      }),
    );

    await expect(getHealth()).resolves.toEqual(healthPayload);
  });

  it("maps the canonical error envelope onto ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({
          error: {
            code: "not_found",
            message: "Resource not found.",
            request_id: "req-123",
          },
        }),
      }),
    );

    const error = await getHealth().catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 404,
      code: "not_found",
      requestId: "req-123",
      message: "Resource not found.",
    });
  });

  it("falls back to a status message when the body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw new Error("not json");
        },
      }),
    );

    const error = await getHealth().catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 502,
      message: "Request failed with status 502",
    });
  });
});
