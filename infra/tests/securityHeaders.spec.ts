/**
 * Cross-check: the TS rendered-content security headers (consumed by the public
 * CloudFront response-headers policy) reproduce the backend's single source of
 * truth byte-for-byte.
 *
 * This reads `backend/src/share/content/headers.py` directly so the two copies
 * can never silently drift: if someone edits the Python CSP/shared headers
 * without updating `securityHeaders.ts` (or vice versa), this fails.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import { expect } from "chai";

import {
  PUBLIC_CACHE_CONTROL,
  SHARED_SECURITY_HEADERS,
  publicResponseHeaders,
} from "../securityHeaders";

const HEADERS_PY = path.resolve(
  __dirname,
  "..",
  "..",
  "backend",
  "src",
  "share",
  "content",
  "headers.py",
);

function readHeadersPy(): string {
  return fs.readFileSync(HEADERS_PY, "utf8");
}

/** Extract a `NAME = "value"` Python string constant. */
function pyConstant(src: string, name: string): string {
  const m = src.match(new RegExp(`${name}\\s*=\\s*"([^"]*)"`));
  if (!m) throw new Error(`Could not find Python constant ${name}`);
  return m[1];
}

/** Extract a `"Header": "value"` entry from the shared-headers dict. */
function pyDictValue(src: string, header: string): string {
  const m = src.match(new RegExp(`"${header}"\\s*:\\s*"([^"]*)"`));
  if (!m) throw new Error(`Could not find dict value for ${header}`);
  return m[1];
}

/** Extract the header NAMES declared in SHARED_SECURITY_HEADERS. */
function pySharedHeaderNames(src: string): string[] {
  const block = src.match(/SHARED_SECURITY_HEADERS: dict\[str, str\] = \{([\s\S]*?)\}/);
  if (!block) throw new Error("Could not find SHARED_SECURITY_HEADERS dict");
  return [...block[1].matchAll(/"([^"]+)"\s*:/g)].map((m) => m[1]);
}

describe("rendered-content security headers (TS mirror of the backend helper)", () => {
  it("emits the same set of shared header names as the backend", () => {
    const names = pySharedHeaderNames(readHeadersPy());
    expect(new Set(Object.keys(SHARED_SECURITY_HEADERS))).to.deep.equal(new Set(names));
  });

  it("byte-matches the backend CSP (sandbox WITHOUT allow-same-origin)", () => {
    const csp = pyConstant(readHeadersPy(), "RENDERED_CONTENT_CSP");
    expect(SHARED_SECURITY_HEADERS["Content-Security-Policy"]).to.equal(csp);
    expect(csp).to.contain("sandbox");
    expect(csp).to.not.contain("allow-same-origin");
  });

  it("byte-matches the remaining shared header values", () => {
    const src = readHeadersPy();
    for (const header of ["X-Content-Type-Options", "Referrer-Policy", "X-Robots-Tag"]) {
      expect(SHARED_SECURITY_HEADERS[header]).to.equal(pyDictValue(src, header));
    }
  });

  it("adds the public-only cache directive on top of the shared set", () => {
    const headers = publicResponseHeaders();
    expect(headers["Cache-Control"]).to.equal(PUBLIC_CACHE_CONTROL);
    expect(PUBLIC_CACHE_CONTROL).to.equal("public, max-age=3600");
    // Every shared header is still present unchanged.
    for (const [k, v] of Object.entries(SHARED_SECURITY_HEADERS)) {
      expect(headers[k]).to.equal(v);
    }
  });
});
