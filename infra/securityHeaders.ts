/**
 * Rendered-content security headers — the TypeScript mirror of the backend's
 * single source of truth (`share.content.headers`).
 *
 * The private content host (slice 07) emits these via
 * `private_rendered_headers()`; the public CloudFront response-headers policy
 * (slice 13) must reproduce the SAME shared headers byte-for-byte so an uploaded
 * artifact is sandboxed identically whether it is served privately (Lambda) or
 * publicly (CloudFront + S3). The CSP `sandbox` WITHOUT `allow-same-origin` is
 * the load-bearing isolation defense and must never gain that directive here.
 *
 * `tests/securityHeaders.spec.ts` cross-checks these constants against the
 * Python source so the two copies can never silently drift.
 */

/**
 * Security headers shared byte-for-byte by every rendered-content host. The
 * names/values and their string form mirror
 * `share.content.headers.SHARED_SECURITY_HEADERS`.
 */
export const SHARED_SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "Content-Security-Policy":
    "sandbox allow-scripts allow-forms allow-popups allow-downloads",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow",
};

/**
 * Public-host cache directive. Unlike the private host (`no-store`), public
 * artifacts are immutable + SHA-addressed, so they are cached at the edge.
 */
export const PUBLIC_CACHE_CONTROL = "public, max-age=3600";

/**
 * The full ordered header set the public CloudFront response-headers policy
 * emits: every shared security header plus the public cache directive.
 */
export function publicResponseHeaders(): Record<string, string> {
  return {
    ...SHARED_SECURITY_HEADERS,
    "Cache-Control": PUBLIC_CACHE_CONTROL,
  };
}
