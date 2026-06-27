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
    dashboardOrigins:
      cfg.getObject<string[]>("dashboardOrigins") ??
      DATA_DEFAULTS.dashboardOrigins,
    tmpExpirationDays:
      cfg.getNumber("tmpExpirationDays") ?? DATA_DEFAULTS.tmpExpirationDays,
  };
}
