import { describe, expect, it } from "vitest";

import { inferSourceType } from "@/lib/sourceType";

describe("inferSourceType", () => {
  it("infers html from common html extensions", () => {
    expect(inferSourceType("page.html")).toBe("html");
    expect(inferSourceType("PAGE.HTM")).toBe("html");
  });

  it("infers markdown from common markdown extensions", () => {
    expect(inferSourceType("notes.md")).toBe("markdown");
    expect(inferSourceType("readme.markdown")).toBe("markdown");
  });

  it("prefers the filename extension over the MIME type", () => {
    expect(inferSourceType("page.html", "text/markdown")).toBe("html");
  });

  it("falls back to the MIME type when the extension is uninformative", () => {
    expect(inferSourceType("clipboard", "text/html")).toBe("html");
    expect(inferSourceType("clipboard", "text/markdown; charset=utf-8")).toBe("markdown");
  });

  it("returns null when nothing yields a supported type", () => {
    expect(inferSourceType("notes.txt")).toBeNull();
    expect(inferSourceType("data", "application/json")).toBeNull();
    expect(inferSourceType("noext")).toBeNull();
  });
});
