import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { request, ApiClientError, api } from "./client";
import * as runtimeConfig from "./runtimeConfig";
import type { HealthData } from "./types";

// Mock the runtimeConfig module
vi.mock("./runtimeConfig");

describe("buildUrl (via request)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("builds a same-origin relative URL when baseUrl is empty", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { status: "healthy" } }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request<HealthData>("/health", {});

    const [url] = mockFetch.mock.calls[0]!;
    expect(url).toBe("/health");
  });

  it("normalizes leading slashes in path", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { status: "healthy" } }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request<HealthData>("//health", {});

    const [url] = mockFetch.mock.calls[0]!;
    expect(url).toBe("/health");
  });

  it("builds an absolute URL when baseUrl is set", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "https://api.example.com",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { status: "healthy" } }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request<HealthData>("/health", {});

    const [url] = mockFetch.mock.calls[0]!;
    expect(url as string).toContain("https://api.example.com");
    expect(url as string).toContain("/health");
  });

  it("appends query parameters as URLSearchParams", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { status: "healthy" } }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request<HealthData>("/events", { query: { workspace_id: "ws-1", task_id: "task-1" } });

    const [url] = mockFetch.mock.calls[0]!;
    expect(url as string).toContain("workspace_id=ws-1");
    expect(url as string).toContain("task_id=task-1");
  });

  it("skips undefined and null query parameter values", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { status: "healthy" } }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request<HealthData>("/events", {
      query: {
        workspace_id: "ws-1",
        task_id: undefined,
        other_param: null,
      },
    });

    const [url] = mockFetch.mock.calls[0]!;
    expect(url as string).toContain("workspace_id=ws-1");
    expect(url as string).not.toContain("task_id");
    expect(url as string).not.toContain("other_param");
  });

  it("converts numeric and boolean query parameters to strings", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { status: "healthy" } }), {
        status: 200,
      })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request<HealthData>("/events", {
      query: { limit: 42, active: true },
    });

    const [url] = mockFetch.mock.calls[0]!;
    expect(url as string).toContain("limit=42");
    expect(url as string).toContain("active=true");
  });
});

describe("request headers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("includes Accept: application/json header", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/health", {});

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).headers).toMatchObject({
      Accept: "application/json",
    });
  });

  it("includes Authorization header with Bearer token when token is present", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "secret-token-123",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/health", {});

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).headers).toMatchObject({
      Authorization: "Bearer secret-token-123",
    });
  });

  it("does not include Authorization header when token is empty", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/health", {});

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).headers).not.toMatchObject({
      Authorization: expect.anything(),
    });
  });

  it("includes Content-Type: application/json when body is present", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/workspaces", { method: "POST", body: { name: "test" } });

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });

  it("does not include Content-Type when body is undefined", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/health", {});

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).headers).not.toMatchObject({
      "Content-Type": expect.anything(),
    });
  });
});

describe("request method and body handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to GET method when not specified", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/health", {});

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).method).toBe("GET");
  });

  it("uses specified HTTP method", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/workspaces", { method: "POST", body: { name: "test" } });

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).method).toBe("POST");
  });

  it("serializes body to JSON string", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    const bodyObj = { name: "test", value: 42 };
    await request("/workspaces", { method: "POST", body: bodyObj });

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).body).toBe(JSON.stringify(bodyObj));
  });

  it("sets body to undefined when not provided", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await request("/health", {});

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).body).toBeUndefined();
  });

  it("passes signal through to fetch", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    const controller = new AbortController();
    const signal = controller.signal;

    await request("/health", { signal });

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).signal).toBe(signal);
  });
});

describe("request error handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("catches network errors and throws ApiClientError with isNetworkError=true", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const networkError = new Error("Network failed");
    const mockFetch = vi.fn().mockRejectedValue(networkError);
    vi.stubGlobal("fetch", mockFetch);

    try {
      await request("/health", {});
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("network_error");
      expect((err as ApiClientError).isNetworkError).toBe(true);
      expect((err as ApiClientError).message).toContain("Network failed");
    }
  });

  it("handles non-JSON responses with invalid_response error", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response("Not JSON", { status: 500 })
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      await request("/health", {});
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("invalid_response");
      expect((err as ApiClientError).status).toBe(500);
    }
  });

  it("extracts error details from ok:false response envelope", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const errorEnvelope = {
      ok: false,
      error: {
        code: "not_found",
        message: "Workspace not found",
        status: 404,
      },
      correlation_id: "corr-123",
    };

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(errorEnvelope), { status: 404 })
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      await request("/workspaces/missing", {});
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("not_found");
      expect((err as ApiClientError).message).toBe("Workspace not found");
      expect((err as ApiClientError).status).toBe(404);
      expect((err as ApiClientError).correlationId).toBe("corr-123");
    }
  });

  it("falls back to HTTP status when envelope status is absent", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const errorEnvelope = {
      ok: false,
      error: {
        code: "internal_error",
        message: "Server error",
        // status omitted
      },
      correlation_id: "corr-456",
    };

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(errorEnvelope), { status: 500 })
    );
    vi.stubGlobal("fetch", mockFetch);

    try {
      await request("/health", {});
      expect.fail("should have thrown");
    } catch (err) {
      expect((err as ApiClientError).status).toBe(500);
    }
  });
});

describe("request success handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps and returns data payload from success envelope", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const data = { workspaces: [{ id: "ws-1", name: "Test" }] };
    const envelope = {
      ok: true,
      data,
      correlation_id: "corr-789",
    };

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(envelope), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    const result = await request("/workspaces", {});

    expect(result).toEqual(data);
  });

  it("handles responses with correlation_id", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const envelope = {
      ok: true,
      data: { status: "ok" },
      correlation_id: "corr-xyz",
    };

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(envelope), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    const result = await request("/health", {});

    expect(result).toEqual({ status: "ok" });
  });
});

describe("ApiClientError", () => {
  it("is an instance of Error", () => {
    const err = new ApiClientError({
      message: "Test error",
      code: "test_code",
      status: 400,
    });

    expect(err).toBeInstanceOf(Error);
  });

  it("sets all constructor properties correctly", () => {
    const err = new ApiClientError({
      message: "Test error",
      code: "test_code",
      status: 400,
      correlationId: "corr-123",
      isNetworkError: true,
    });

    expect(err.message).toBe("Test error");
    expect(err.code).toBe("test_code");
    expect(err.status).toBe(400);
    expect(err.correlationId).toBe("corr-123");
    expect(err.isNetworkError).toBe(true);
  });

  it("defaults isNetworkError to false when not specified", () => {
    const err = new ApiClientError({
      message: "Test error",
      code: "test_code",
      status: 400,
    });

    expect(err.isNetworkError).toBe(false);
  });

  it("has name 'ApiClientError'", () => {
    const err = new ApiClientError({
      message: "Test error",
      code: "test_code",
      status: 400,
    });

    expect(err.name).toBe("ApiClientError");
  });
});

describe("api.getEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls request with correct path and query parameters", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { events: [] } }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    await api.getEvents({ workspaceId: "ws-1", taskId: "task-1" });

    const [url] = mockFetch.mock.calls[0]!;
    expect(url as string).toContain("/events");
    expect(url as string).toContain("workspace_id=ws-1");
    expect(url as string).toContain("task_id=task-1");
  });

  it("passes signal through to request", async () => {
    vi.mocked(runtimeConfig.getRuntimeConfig).mockReturnValue({
      baseUrl: "",
      token: "",
    });

    const mockFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { events: [] } }), { status: 200 })
    );
    vi.stubGlobal("fetch", mockFetch);

    const controller = new AbortController();
    const signal = controller.signal;

    await api.getEvents({ workspaceId: "ws-1", taskId: "task-1" }, signal);

    const [, options] = mockFetch.mock.calls[0]!;
    expect((options as RequestInit).signal).toBe(signal);
  });
});
