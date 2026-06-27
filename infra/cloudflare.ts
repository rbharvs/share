/**
 * Cloudflare layer: the DNS records that point the three hosts at AWS, plus the
 * two Zero Trust Access applications that gate the private hosts.
 *
 * Security/PRD invariants encoded here (asserted by `tests/cloudflare.spec.ts`):
 *
 * - DNS: the two PRIVATE hosts (`share.example.com`, `private.usercontent.example`)
 *   are PROXIED (orange-cloud) CNAMEs to their API Gateway regional domains, so
 *   ingress is forced through Cloudflare (where Access + the IP allowlist apply).
 *   The PUBLIC host (`public.usercontent.example`) is a DNS-ONLY CNAME straight to
 *   CloudFront — it must never reach Lambda.
 * - Access: TWO separate self-hosted applications with DISTINCT audiences (one
 *   per private host), each a 7-day session and an owner-only allow policy. The
 *   per-host AUD is the cross-host replay defense; mixing the two hosts into one
 *   app would share an AUD and break it.
 * - AccessConfig mirroring (slice 02): the issuer + each app's generated AUD are
 *   surfaced as outputs and fed straight into the Lambda env (see `index.ts` →
 *   `compute.ts`). Pulumi is the single source of truth, so the Cloudflare apps
 *   and the backend verifier cannot silently drift. The LOCAL issuer/audiences
 *   live only in `Settings.for_local` and are never produced here.
 *
 * Construction is a pure function of {@link CloudflareConfig} + an injected
 * provider so the focused config checks run under Pulumi's unit-test mocks
 * without touching Cloudflare.
 */

import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";

import type { CloudflareConfig } from "./config";

/** PRD 7-day Access session, in Cloudflare's duration form. */
export const SESSION_DURATION_7_DAYS = "168h";

/** Self-hosted application type for both private-host Access apps. */
export const ACCESS_APP_TYPE = "self_hosted";

/** CNAME record type for every host record. */
export const CNAME = "CNAME";

/** Proxied records use Cloudflare "automatic" TTL (must be 1 when proxied). */
export const PROXIED_TTL = 1;

/** DNS-only records may carry a real TTL; 5 minutes is plenty for the public host. */
export const DNS_ONLY_TTL = 300;

/**
 * The Access issuer for a team-domain slug:
 * `https://<slug>.cloudflareaccess.com`. The backend verifier checks this `iss`
 * exactly, so it is derived (never the localhost dev issuer) and mirrored into
 * the Lambda env.
 */
export function accessIssuer(teamDomain: string): string {
  return `https://${teamDomain}.cloudflareaccess.com`;
}

/** The JWKS endpoint Cloudflare publishes for an Access issuer. */
export function accessJwksUrl(issuer: string): string {
  return `${issuer}/cdn-cgi/access/certs`;
}

// --- Access applications ---------------------------------------------------

export interface CloudflareAccessInputs {
  readonly cfg: CloudflareConfig;
  readonly provider: cloudflare.Provider;
}

export interface CloudflareAccessResources {
  /** Derived Access issuer (`iss`) the verifier accepts. */
  readonly issuer: string;
  /** Cloudflare JWKS endpoint the verifier fetches signing keys from. */
  readonly jwksUrl: string;
  readonly dashboardApp: cloudflare.ZeroTrustAccessApplication;
  readonly privateApp: cloudflare.ZeroTrustAccessApplication;
  readonly dashboardPolicy: cloudflare.ZeroTrustAccessPolicy;
  readonly privatePolicy: cloudflare.ZeroTrustAccessPolicy;
  /** Cloudflare-generated AUD tag for the dashboard host (mirrored to Lambda). */
  readonly dashboardAudience: pulumi.Output<string>;
  /** Cloudflare-generated AUD tag for the private host (mirrored to Lambda). */
  readonly privateAudience: pulumi.Output<string>;
}

/**
 * Create the two Zero Trust Access applications (dashboard + private content),
 * each with its own owner-only allow policy and a 7-day session. The two apps
 * stay SEPARATE precisely so they get DISTINCT AUDs — the per-host replay
 * defense the verifier relies on.
 */
export function createCloudflareAccess(
  inputs: CloudflareAccessInputs,
): CloudflareAccessResources {
  const { cfg, provider } = inputs;
  const opts: pulumi.CustomResourceOptions = { provider };

  const issuer = accessIssuer(cfg.teamDomain);
  const jwksUrl = accessJwksUrl(issuer);

  const buildApp = (
    key: string,
    host: string,
  ): {
    app: cloudflare.ZeroTrustAccessApplication;
    policy: cloudflare.ZeroTrustAccessPolicy;
  } => {
    // Owner-only allow policy: only the single allowlisted email may pass.
    const policy = new cloudflare.ZeroTrustAccessPolicy(
      `${key}-access-policy`,
      {
        accountId: cfg.accountId,
        name: `share ${key} owner-only`,
        decision: "allow",
        includes: [{ email: { email: cfg.allowedOwnerEmail } }],
      },
      opts,
    );

    const app = new cloudflare.ZeroTrustAccessApplication(
      `${key}-access-app`,
      {
        accountId: cfg.accountId,
        name: `share ${key}`,
        type: ACCESS_APP_TYPE,
        domain: host,
        // 7-day session (PRD).
        sessionDuration: cfg.sessionDuration,
        // Personal owner-only tool: no app-launcher tile, no IdP auto-redirect.
        appLauncherVisible: false,
        autoRedirectToIdentity: false,
        // Attach the owner-only policy created above.
        policies: [{ id: policy.id, precedence: 1 }],
      },
      opts,
    );

    return { app, policy };
  };

  const dashboard = buildApp("dashboard", cfg.dashboardHost);
  const priv = buildApp("private", cfg.privateHost);

  return {
    issuer,
    jwksUrl,
    dashboardApp: dashboard.app,
    privateApp: priv.app,
    dashboardPolicy: dashboard.policy,
    privatePolicy: priv.policy,
    dashboardAudience: dashboard.app.aud,
    privateAudience: priv.app.aud,
  };
}

// --- DNS records -----------------------------------------------------------

export interface CloudflareDnsInputs {
  readonly cfg: CloudflareConfig;
  readonly provider: cloudflare.Provider;
  /** API Gateway regional domain backing the dashboard host (proxied CNAME). */
  readonly dashboardApiTarget: pulumi.Input<string>;
  /** API Gateway regional domain backing the private host (proxied CNAME). */
  readonly privateApiTarget: pulumi.Input<string>;
  /** CloudFront distribution domain for the public host (DNS-only CNAME). */
  readonly publicCloudFrontDomain: pulumi.Input<string>;
}

export interface CloudflareDnsResources {
  readonly dashboardRecord: cloudflare.DnsRecord;
  readonly privateRecord: cloudflare.DnsRecord;
  readonly publicRecord: cloudflare.DnsRecord;
}

/**
 * Create the three host DNS records. The two private hosts are PROXIED so all
 * traffic is forced through Cloudflare (Access + the API Gateway IP allowlist);
 * the public host is DNS-ONLY straight to CloudFront so it never touches Lambda.
 */
export function createCloudflareDns(
  inputs: CloudflareDnsInputs,
): CloudflareDnsResources {
  const { cfg, provider } = inputs;
  const opts: pulumi.CustomResourceOptions = { provider };

  // Dashboard host lives on the example.com zone; both usercontent.example
  // hosts share the usercontent.example zone.
  const dashboardRecord = new cloudflare.DnsRecord(
    "dashboard-dns",
    {
      zoneId: cfg.dashboardZoneId,
      name: cfg.dashboardHost,
      type: CNAME,
      content: inputs.dashboardApiTarget,
      proxied: true,
      ttl: PROXIED_TTL,
    },
    opts,
  );

  const privateRecord = new cloudflare.DnsRecord(
    "private-dns",
    {
      zoneId: cfg.contentZoneId,
      name: cfg.privateHost,
      type: CNAME,
      content: inputs.privateApiTarget,
      proxied: true,
      ttl: PROXIED_TTL,
    },
    opts,
  );

  // PUBLIC host: DNS-only to CloudFront. Proxying here would route public,
  // unauthenticated, intentionally-arbitrary content through Cloudflare/Lambda;
  // it must resolve straight to the CDN.
  const publicRecord = new cloudflare.DnsRecord(
    "public-dns",
    {
      zoneId: cfg.contentZoneId,
      name: cfg.publicHost,
      type: CNAME,
      content: inputs.publicCloudFrontDomain,
      proxied: false,
      ttl: DNS_ONLY_TTL,
    },
    opts,
  );

  return { dashboardRecord, privateRecord, publicRecord };
}
