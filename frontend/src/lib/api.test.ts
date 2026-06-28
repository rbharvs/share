import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  CSRF_HEADER,
  CSRF_TOKEN,
  presignUpload,
  publishContent,
  unpublishContent,
} from "@/lib/api";

function jsonResponse(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dashboard POST helpers", () => {
  it("sends the CSRF header, POST method and a relative URL", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ upload_id: "u1", url: "https://s3", fields: {}, max_size_bytes: 1 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await presignUpload({ filename: "a.html", source_type: "html" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/uploads/presign");
    expect(init.method).toBe("POST");
    const headers = init.headers as Record<string, string>;
    expect(headers[CSRF_HEADER]).toBe(CSRF_TOKEN);
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body as string)).toEqual({
      filename: "a.html",
      source_type: "html",
    });
  });

  it("encodes the sha into the publish/unpublish path", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse({ sha256: "abc" })));
    vi.stubGlobal("fetch", fetchMock);

    await publishContent("abc123");
    await unpublishContent("abc123");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/content/abc123/publish");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/content/abc123/unpublish");
  });

  it("decodes a structured error envelope into an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: "validation_error",
              message: "Request origin is not allowed.",
              request_id: "req-7",
            },
          },
          { status: 400 },
        ),
      ),
    );

    await expect(publishContent("abc")).rejects.toMatchObject({
      code: "validation_error",
      message: "Request origin is not allowed.",
      requestId: "req-7",
      status: 400,
    });
  });

  it("wraps a network failure as a network_error ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    const err = await publishContent("abc").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("network_error");
  });
});
