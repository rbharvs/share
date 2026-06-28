/**
 * Resolved data-layer configuration.
 *
 * The backend settings provider (slice 01, `share.config.settings.Settings`) is
 * the single source of truth for resource *names*: the table and bucket names
 * here MUST match the `table_name` / `private_bucket` / `public_bucket` defaults
 * the running Lambda reads, or the deployed app would point at resources Pulumi
 * never created. The defaults below mirror those settings; a `share:*` Pulumi
 * config key can override any of them per stack without code changes.
 */

import * as pulumi from "@pulumi/pulumi";

/** Plain (non-Pulumi) shape so {@link createDataResources} stays unit-testable. */
export interface DataConfig {
  /** AWS region for every stateful resource (PRD: `us-east-1`). */
  readonly region: string;
  /** DynamoDB single-table name. Mirrors backend `Settings.table_name`. */
  readonly tableName: string;
  /** TTL attribute for upload-session expiry (PRD: `expires_at_epoch`). */
  readonly ttlAttribute: string;
  /** Private bucket name. Mirrors backend `Settings.private_bucket`. */
  readonly privateBucket: string;
  /** Public bucket name. Mirrors backend `Settings.public_bucket`. */
  readonly publicBucket: string;
  /** Origins allowed by the private bucket's presigned-POST CORS rule. */
  readonly dashboardOrigins: readonly string[];
  /** Days after which abandoned `tmp/` objects expire (PRD: ~1 day). */
  readonly tmpExpirationDays: number;
}

/** Defaults that mirror the backend settings provider (the naming source of truth). */
export const DATA_DEFAULTS = {
  region: "us-east-1",
  tableName: "share",
  ttlAttribute: "expires_at_epoch",
  privateBucket: "share-private",
  publicBucket: "share-public",
  dashboardOrigins: ["https://share.example.com"],
  tmpExpirationDays: 1,
} as const;

/**
 * Build the {@link DataConfig} from Pulumi stack config, falling back to the
 * backend-mirroring {@link DATA_DEFAULTS}. Region resolves from the standard
 * `aws:region` key first so it stays consistent with the AWS provider.
 */
export function loadDataConfig(): DataConfig {
  const cfg = new pulumi.Config("share");
  const awsRegion = new pulumi.Config("aws").get("region");

  return {
    region: awsRegion ?? cfg.get("region") ?? DATA_DEFAULTS.region,
    tableName: cfg.get("tableName") ?? DATA_DEFAULTS.tableName,
    ttlAttribute: cfg.get("ttlAttribute") ?? DATA_DEFAULTS.ttlAttribute,
    privateBucket: cfg.get("privateBucket") ?? DATA_DEFAULTS.privateBucket,
    publicBucket: cfg.get("publicBucket") ?? DATA_DEFAULTS.publicBucket,
    dashboardOrigins: cfg.getObject<string[]>("dashboardOrigins") ?? DATA_DEFAULTS.dashboardOrigins,
    tmpExpirationDays: cfg.getNumber("tmpExpirationDays") ?? DATA_DEFAULTS.tmpExpirationDays,
  };
}

// --- Edge (compute + CDN) configuration ------------------------------------

/**
 * Resolved configuration for the compute (Lambda + API Gateway) and CDN
 * (CloudFront) layers. Like {@link DataConfig} this is a plain shape so the
 * resource constructors stay unit-testable under Pulumi mocks.
 *
 * The host names mirror the backend settings provider
 * (`share.config.settings.Settings`): `share.example.com` and
 * `private.usercontent.example` are the two PRIVATE hosts fronting the same
 * API-Gateway/Lambda; `public.usercontent.example` is the PUBLIC host served only
 * by CloudFront. The Lambda runtime contract (py3.12 / arm64 / 512 MB / 30 s /
 * Mangum handler) is PRD-mandated and overridable per stack.
 */
export interface EdgeConfig {
  /** AWS region for every edge resource (PRD: `us-east-1`). */
  readonly region: string;
  /** Dashboard + mutation-API host. Mirrors backend `Settings.dashboard_host`. */
  readonly dashboardHost: string;
  /** Authenticated private content host. Mirrors `Settings.private_host`. */
  readonly privateHost: string;
  /** Unauthenticated public content host. Mirrors `Settings.public_host`. */
  readonly publicHost: string;
  /** Lambda memory in MB (PRD: 512). */
  readonly lambdaMemoryMb: number;
  /** Lambda timeout in seconds (PRD: 30). */
  readonly lambdaTimeoutSeconds: number;
  /** Mangum handler path (`module.attr`), matching `share/handler.py`. */
  readonly lambdaHandler: string;
  /** CloudWatch retention for Lambda + API logs (PRD: 30 days). */
  readonly logRetentionDays: number;
}

/** Defaults mirroring the backend settings provider + PRD Lambda contract. */
export const EDGE_DEFAULTS = {
  region: DATA_DEFAULTS.region,
  dashboardHost: "share.example.com",
  privateHost: "private.usercontent.example",
  publicHost: "public.usercontent.example",
  lambdaMemoryMb: 512,
  lambdaTimeoutSeconds: 30,
  lambdaHandler: "share.handler.handler",
  logRetentionDays: 30,
} as const;

/** Build the {@link EdgeConfig} from Pulumi stack config + {@link EDGE_DEFAULTS}. */
export function loadEdgeConfig(): EdgeConfig {
  const cfg = new pulumi.Config("share");
  const awsRegion = new pulumi.Config("aws").get("region");

  return {
    region: awsRegion ?? cfg.get("region") ?? EDGE_DEFAULTS.region,
    dashboardHost: cfg.get("dashboardHost") ?? EDGE_DEFAULTS.dashboardHost,
    privateHost: cfg.get("privateHost") ?? EDGE_DEFAULTS.privateHost,
    publicHost: cfg.get("publicHost") ?? EDGE_DEFAULTS.publicHost,
    lambdaMemoryMb: cfg.getNumber("lambdaMemoryMb") ?? EDGE_DEFAULTS.lambdaMemoryMb,
    lambdaTimeoutSeconds:
      cfg.getNumber("lambdaTimeoutSeconds") ?? EDGE_DEFAULTS.lambdaTimeoutSeconds,
    lambdaHandler: cfg.get("lambdaHandler") ?? EDGE_DEFAULTS.lambdaHandler,
    logRetentionDays: cfg.getNumber("logRetentionDays") ?? EDGE_DEFAULTS.logRetentionDays,
  };
}

// --- Cloudflare (DNS + Access) configuration -------------------------------

/**
 * Resolved configuration for the Cloudflare layer: the DNS records that point
 * the three hosts at AWS, and the two Zero Trust Access applications that gate
 * the private hosts.
 *
 * Two zones are involved because the hosts live on two apex domains:
 * `share.example.com` (zone `example.com`) and the two
 * `*.usercontent.example` hosts (zone `usercontent.example`). The account/zone ids
 * are real Cloudflare identifiers with no meaningful default — they MUST be set
 * per stack (`pulumi config set share:cloudflareAccountId …`, etc.); the empty
 * defaults only let `pulumi preview`/typecheck run before a stack is configured.
 *
 * `allowedOwnerEmail` is plain config, NOT a secret (PRD): the SHA URLs are not
 * secrets and the owner allowlist is just an email. The Access AUD tags, by
 * contrast, originate in Cloudflare and are the per-host cross-host replay
 * defense — they are surfaced as resource outputs (never hand-copied) and
 * mirrored into the Lambda env so the verifier and Cloudflare cannot drift.
 */
export interface CloudflareConfig {
  /** Cloudflare account id that owns the Access apps/policies. */
  readonly accountId: string;
  /** Zone id for `example.com` (the dashboard host's apex). */
  readonly dashboardZoneId: string;
  /** Zone id for `usercontent.example` (the private + public hosts' apex). */
  readonly contentZoneId: string;
  /** Dashboard + mutation-API host (proxied DNS). Mirrors `EdgeConfig`. */
  readonly dashboardHost: string;
  /** Authenticated private content host (proxied DNS). Mirrors `EdgeConfig`. */
  readonly privateHost: string;
  /** Unauthenticated public content host (DNS-only to CloudFront). */
  readonly publicHost: string;
  /** Owner allowlist email for both Access policies (plain config, not secret). */
  readonly allowedOwnerEmail: string;
  /** Cloudflare Access team domain slug → issuer `https://<slug>.cloudflareaccess.com`. */
  readonly teamDomain: string;
  /** Access session duration (PRD: 7 days → Cloudflare `"168h"`). */
  readonly sessionDuration: string;
}

/** Defaults mirroring the backend settings provider + PRD Access contract. */
export const CLOUDFLARE_DEFAULTS = {
  accountId: "",
  dashboardZoneId: "",
  contentZoneId: "",
  dashboardHost: EDGE_DEFAULTS.dashboardHost,
  privateHost: EDGE_DEFAULTS.privateHost,
  publicHost: EDGE_DEFAULTS.publicHost,
  // Mirrors backend `Settings.allowed_owner_email` (the single allowlist).
  allowedOwnerEmail: "owner@example.com",
  teamDomain: "myteam",
  // 7-day session (PRD). Cloudflare accepts a fixed duration enum; "168h" = 7d.
  sessionDuration: "168h",
} as const;

/** Build the {@link CloudflareConfig} from Pulumi stack config + defaults. */
export function loadCloudflareConfig(): CloudflareConfig {
  const cfg = new pulumi.Config("share");

  return {
    accountId: cfg.get("cloudflareAccountId") ?? CLOUDFLARE_DEFAULTS.accountId,
    dashboardZoneId: cfg.get("dashboardZoneId") ?? CLOUDFLARE_DEFAULTS.dashboardZoneId,
    contentZoneId: cfg.get("contentZoneId") ?? CLOUDFLARE_DEFAULTS.contentZoneId,
    dashboardHost: cfg.get("dashboardHost") ?? CLOUDFLARE_DEFAULTS.dashboardHost,
    privateHost: cfg.get("privateHost") ?? CLOUDFLARE_DEFAULTS.privateHost,
    publicHost: cfg.get("publicHost") ?? CLOUDFLARE_DEFAULTS.publicHost,
    allowedOwnerEmail: cfg.get("allowedOwnerEmail") ?? CLOUDFLARE_DEFAULTS.allowedOwnerEmail,
    teamDomain: cfg.get("cloudflareTeamDomain") ?? CLOUDFLARE_DEFAULTS.teamDomain,
    sessionDuration: cfg.get("accessSessionDuration") ?? CLOUDFLARE_DEFAULTS.sessionDuration,
  };
}
