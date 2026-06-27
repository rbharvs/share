/**
 * Checked-in Cloudflare edge IP ranges.
 *
 * The API Gateway resource policy (slice 13) allows `execute-api:Invoke` ONLY
 * from these source ranges — defense in depth on top of Cloudflare Access and
 * app-level JWT verification, so the regional API endpoint cannot be reached
 * except through Cloudflare's proxy.
 *
 * PRD decision: these are checked in, NOT fetched dynamically on every Pulumi
 * run in v1. They mirror Cloudflare's published lists
 * (https://www.cloudflare.com/ips-v4 / -v6); a future helper can refresh them.
 */

/** Cloudflare published IPv4 CIDR ranges. */
export const CLOUDFLARE_IPV4_RANGES: readonly string[] = [
  "173.245.48.0/20",
  "103.21.244.0/22",
  "103.22.200.0/22",
  "103.31.4.0/22",
  "141.101.64.0/18",
  "108.162.192.0/18",
  "190.93.240.0/20",
  "188.114.96.0/20",
  "197.234.240.0/22",
  "198.41.128.0/17",
  "162.158.0.0/15",
  "104.16.0.0/13",
  "104.24.0.0/14",
  "172.64.0.0/13",
  "131.0.72.0/22",
];

/** Cloudflare published IPv6 CIDR ranges. */
export const CLOUDFLARE_IPV6_RANGES: readonly string[] = [
  "2400:cb00::/32",
  "2606:4700::/32",
  "2803:f800::/32",
  "2405:b500::/32",
  "2405:8100::/32",
  "2a06:98c0::/29",
  "2c0f:f248::/32",
];

/** Every checked-in Cloudflare range (IPv4 then IPv6). */
export const CLOUDFLARE_IP_RANGES: readonly string[] = [
  ...CLOUDFLARE_IPV4_RANGES,
  ...CLOUDFLARE_IPV6_RANGES,
];
