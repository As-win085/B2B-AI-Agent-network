import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest, configureAuth, getHealth, setAccessToken } from "../api/client";

const healthPayload = {
  status: "ok",
  service: "Asama.ai API",
  version: "0.2.0",
  environment: "test",
  timestamp: "2026-11-14T07:00:00Z",
};

afterEach(() => {
  configureAuth(null);
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

  it("attaches the in-memory access token to authenticated requests", async () => {
    setAccessToken("access-token");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: { ok: true } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/v1/auth/me");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer access-token");
  });

  it("refreshes once and retries a 401 with the new access token", async () => {
    const refreshAccessToken = vi.fn().mockResolvedValue("fresh-token");
    const onSessionExpired = vi.fn();
    configureAuth({ refreshAccessToken, onSessionExpired });
    setAccessToken("stale-token");

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ error: { code: "token_expired", message: "Expired." } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ data: { ok: true } }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/api/v1/auth/me")).resolves.toEqual({ ok: true });

    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(onSessionExpired).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const retryInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect(new Headers(retryInit.headers).get("Authorization")).toBe("Bearer fresh-token");
  });

  it("coalesces concurrent refreshes into a single request", async () => {
    let releaseRefresh: (token: string) => void = () => undefined;
    const refreshAccessToken = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          releaseRefresh = resolve;
        }),
    );
    configureAuth({ refreshAccessToken, onSessionExpired: vi.fn() });
    setAccessToken("stale-token");

    const unauthorized = {
      ok: false,
      status: 401,
      json: async () => ({ error: { code: "token_expired", message: "Expired." } }),
    };
    const authorized = {
      ok: true,
      status: 200,
      json: async () => ({ data: { ok: true } }),
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(unauthorized)
        .mockResolvedValueOnce(unauthorized)
        .mockResolvedValue(authorized),
    );

    const first = apiRequest("/api/v1/auth/me");
    const second = apiRequest("/api/v1/organizations");

    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    releaseRefresh("fresh-token");

    await expect(Promise.all([first, second])).resolves.toEqual([{ ok: true }, { ok: true }]);
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
  });
});
