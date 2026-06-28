/**
 * Stateful AWS data layer for `share`: the DynamoDB single table plus the two
 * separate S3 buckets (private + public).
 *
 * Security/PRD invariants encoded here (asserted by `tests/data.spec.ts`):
 *
 * - One DynamoDB table, `PAY_PER_REQUEST`, point-in-time recovery on, TTL on the
 *   upload-session expiry attribute.
 * - Two *separate* buckets, both default-SSE, neither versioned.
 * - `tmp/` expires after ~1 day; `raw/` and `artifacts/` never expire.
 * - The private bucket's only CORS rule allows just the dashboard origin(s) and
 *   `POST` (the presigned upload); everything blocks public access.
 * - The public bucket stays private (all public access blocked) — it is reached
 *   only through CloudFront Origin Access Control, wired in slice 13.
 *
 * Construction is a pure function of {@link DataConfig} so the focused config
 * checks can drive it under Pulumi's unit-test mocks without touching AWS.
 */

import * as aws from "@pulumi/aws";
import * as pulumi from "@pulumi/pulumi";

import type { DataConfig } from "./config";

/** Hash/range key names of the single table (PRD single-table design). */
export const TABLE_HASH_KEY = "pk";
export const TABLE_RANGE_KEY = "sk";

/** Lifecycle-rule id + prefix for abandoned temporary uploads. */
export const TMP_LIFECYCLE_RULE_ID = "expire-tmp";
export const TMP_PREFIX = "tmp/";

/** Outputs consumed by the compute/CDN slice (13) and by the config checks. */
export interface DataResources {
  readonly provider: aws.Provider;
  readonly table: aws.dynamodb.Table;
  readonly privateBucket: aws.s3.BucketV2;
  readonly publicBucket: aws.s3.BucketV2;
  readonly privateBucketSse: aws.s3.BucketServerSideEncryptionConfigurationV2;
  readonly publicBucketSse: aws.s3.BucketServerSideEncryptionConfigurationV2;
  readonly privateBucketVersioning: aws.s3.BucketVersioningV2;
  readonly publicBucketVersioning: aws.s3.BucketVersioningV2;
  readonly privateBucketCors: aws.s3.BucketCorsConfigurationV2;
  readonly privateBucketLifecycle: aws.s3.BucketLifecycleConfigurationV2;
  readonly privateBucketAccessBlock: aws.s3.BucketPublicAccessBlock;
  readonly publicBucketAccessBlock: aws.s3.BucketPublicAccessBlock;
}

/** Apply default SSE (SSE-S3 / AES256) to a bucket (PRD: default encryption). */
function encryptBucket(
  name: string,
  bucket: aws.s3.BucketV2,
  opts: pulumi.CustomResourceOptions,
): aws.s3.BucketServerSideEncryptionConfigurationV2 {
  return new aws.s3.BucketServerSideEncryptionConfigurationV2(
    name,
    {
      bucket: bucket.id,
      rules: [{ applyServerSideEncryptionByDefault: { sseAlgorithm: "AES256" } }],
    },
    opts,
  );
}

/** Explicitly leave a bucket unversioned (PRD: no S3 versioning in v1). */
function disableVersioning(
  name: string,
  bucket: aws.s3.BucketV2,
  opts: pulumi.CustomResourceOptions,
): aws.s3.BucketVersioningV2 {
  return new aws.s3.BucketVersioningV2(
    name,
    {
      bucket: bucket.id,
      // "Disabled" (valid only at creation) keeps a brand-new bucket unversioned
      // rather than the "Suspended" state used to turn versioning back off.
      versioningConfiguration: { status: "Disabled" },
    },
    opts,
  );
}

/** Block all four public-access vectors on a bucket. */
function blockPublicAccess(
  name: string,
  bucket: aws.s3.BucketV2,
  opts: pulumi.CustomResourceOptions,
): aws.s3.BucketPublicAccessBlock {
  return new aws.s3.BucketPublicAccessBlock(
    name,
    {
      bucket: bucket.id,
      blockPublicAcls: true,
      blockPublicPolicy: true,
      ignorePublicAcls: true,
      restrictPublicBuckets: true,
    },
    opts,
  );
}

/**
 * Create the DynamoDB table and both S3 buckets with all their attached
 * configuration, pinned to {@link DataConfig.region}.
 */
export function createDataResources(cfg: DataConfig): DataResources {
  const provider = new aws.Provider("aws", {
    region: cfg.region as aws.Region,
  });
  const opts: pulumi.CustomResourceOptions = { provider };

  // --- DynamoDB single table -------------------------------------------------
  const table = new aws.dynamodb.Table(
    "metadata",
    {
      name: cfg.tableName,
      billingMode: "PAY_PER_REQUEST",
      hashKey: TABLE_HASH_KEY,
      rangeKey: TABLE_RANGE_KEY,
      attributes: [
        { name: TABLE_HASH_KEY, type: "S" },
        { name: TABLE_RANGE_KEY, type: "S" },
      ],
      // Continuous backups so a bad write/delete is recoverable.
      pointInTimeRecovery: { enabled: true },
      // Upload sessions self-expire (~1h) via this epoch-seconds attribute.
      ttl: { attributeName: cfg.ttlAttribute, enabled: true },
    },
    opts,
  );

  // --- Private bucket --------------------------------------------------------
  const privateBucket = new aws.s3.BucketV2("private", { bucket: cfg.privateBucket }, opts);
  const privateBucketSse = encryptBucket("private-sse", privateBucket, opts);
  const privateBucketVersioning = disableVersioning("private-versioning", privateBucket, opts);
  const privateBucketAccessBlock = blockPublicAccess(
    "private-public-access-block",
    privateBucket,
    opts,
  );

  // Only `tmp/` expires; `raw/` (canonical source) and `artifacts/` (rendered
  // private artifact) are immutable and kept indefinitely in v1.
  const privateBucketLifecycle = new aws.s3.BucketLifecycleConfigurationV2(
    "private-lifecycle",
    {
      bucket: privateBucket.id,
      rules: [
        {
          id: TMP_LIFECYCLE_RULE_ID,
          status: "Enabled",
          filter: { prefix: TMP_PREFIX },
          expiration: { days: cfg.tmpExpirationDays },
          // Reap stranded multipart parts from abandoned presigned uploads too.
          abortIncompleteMultipartUpload: {
            daysAfterInitiation: cfg.tmpExpirationDays,
          },
        },
      ],
    },
    opts,
  );

  // Browser presigned-POST upload: the dashboard origin(s) may POST directly to
  // the private bucket. No GET/PUT/DELETE and no other origin is allowed.
  const privateBucketCors = new aws.s3.BucketCorsConfigurationV2(
    "private-cors",
    {
      bucket: privateBucket.id,
      corsRules: [
        {
          allowedMethods: ["POST"],
          allowedOrigins: [...cfg.dashboardOrigins],
          allowedHeaders: ["*"],
          exposeHeaders: ["ETag", "Location"],
          maxAgeSeconds: 3000,
        },
      ],
    },
    opts,
  );

  // --- Public bucket ---------------------------------------------------------
  // Stays *private*: served only through CloudFront OAC (the bucket policy that
  // grants the distribution access is added in slice 13).
  const publicBucket = new aws.s3.BucketV2("public", { bucket: cfg.publicBucket }, opts);
  const publicBucketSse = encryptBucket("public-sse", publicBucket, opts);
  const publicBucketVersioning = disableVersioning("public-versioning", publicBucket, opts);
  const publicBucketAccessBlock = blockPublicAccess(
    "public-public-access-block",
    publicBucket,
    opts,
  );

  return {
    provider,
    table,
    privateBucket,
    publicBucket,
    privateBucketSse,
    publicBucketSse,
    privateBucketVersioning,
    publicBucketVersioning,
    privateBucketCors,
    privateBucketLifecycle,
    privateBucketAccessBlock,
    publicBucketAccessBlock,
  };
}
