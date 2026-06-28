import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { MAX_UPLOAD_BYTES, runUpload, uploadToS3 } from "@/lib/upload";
import type { PresignResponse } from "@/lib/types";

interface ProgressEventLike {
  lengthComputable: boolean;
  loaded: number;
  total: number;
}

/** A minimal XMLHttpRequest stand-in that drives the upload state machine. */
class FakeXHR {
  static nextStatus = 204;
  static mode: "ok" | "error" | "abort" = "ok";
  static lastSentKeys: string[] = [];

  method = "";
  url = "";
  status = 0;
  upload: { onprogress: ((e: ProgressEventLike) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  send(form: FormData): void {
    FakeXHR.lastSentKeys = [...form.keys()];
    queueMicrotask(() => {
      if (FakeXHR.mode === "error") return this.onerror?.();
      if (FakeXHR.mode === "abort") return this.onabort?.();
      this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
      this.upload.onprogress?.({ lengthComputable: true, loaded: 10, total: 10 });
      this.status = FakeXHR.nextStatus;
      this.onload?.();
    });
  }
}

const presign: PresignResponse = {
  upload_id: "u-1",
  url: "https://bucket.s3.amazonaws.com/",
  fields: { key: "tmp/u-1", policy: "p", "x-amz-signature": "sig" },
  max_size_bytes: MAX_UPLOAD_BYTES,
};

beforeEach(() => {
  FakeXHR.nextStatus = 204;
  FakeXHR.mode = "ok";
  FakeXHR.lastSentKeys = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("uploadToS3", () => {
  it("posts the presigned fields before the file part and reports progress", async () => {
    const file = new File(["<h1>hi</h1>"], "a.html", { type: "text/html" });
    const progress: number[] = [];

    await uploadToS3(presign, file, (p) => progress.push(p.loaded));

    // Fields must precede the file; S3 ignores fields that follow it.
    expect(FakeXHR.lastSentKeys).toEqual(["key", "policy", "x-amz-signature", "file"]);
    expect(progress).toEqual([5, 10]);
  });

  it("rejects a non-2xx S3 response (e.g. an oversized policy rejection)", async () => {
    FakeXHR.nextStatus = 403;
    const file = new File(["x"], "a.html", { type: "text/html" });

    const err = await uploadToS3(presign, file).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("upload_rejected");
  });

  it("rejects a network/transport failure", async () => {
    FakeXHR.mode = "error";
    const file = new File(["x"], "a.html", { type: "text/html" });

    const err = await uploadToS3(presign, file).catch((e) => e);
    expect(err.code).toBe("network_error");
  });
});

describe("runUpload", () => {
  it("rejects an oversized file locally without any network call", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const big = new File([new Uint8Array(MAX_UPLOAD_BYTES + 1)], "big.html", {
      type: "text/html",
    });

    const err = await runUpload(big, "html").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("upload_too_large");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("runs presign -> S3 -> finalize and returns the content item", async () => {
    const item = { sha256: "abc", status: "uploaded" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(presign), {
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(item), {
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["<h1>hi</h1>"], "a.html", { type: "text/html" });
    const result = await runUpload(file, "html");

    expect(result).toMatchObject(item);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/uploads/presign");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/uploads/finalize");
    // Finalize carries only the upload_id (no re-asserted filename/type).
    const finalizeBody = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
    expect(finalizeBody).toEqual({ upload_id: "u-1" });
    expect(FakeXHR.lastSentKeys).toContain("file");
  });
});
