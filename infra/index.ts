/**
 * Pulumi entrypoint for the `share` infrastructure (AWS + Cloudflare).
 *
 * Slice 12 fills in the stateful data layer (DynamoDB single table + private and
 * public S3 buckets). The remaining stack is filled in by:
 *   - slice 13: Lambda + API Gateway (REST) + CloudFront/OAC + ACM
 *   - slice 14: Cloudflare DNS records + Access apps/policies + deploy wiring
 *
 * The Lambda is deployed from the PREBUILT zip emitted by `make build`
 * (`backend/dist/lambda.zip`). Pulumi treats it as an opaque input — no frontend
 * build, no dependency vendoring, and no Docker happen during `pulumi preview`.
 */

import * as path from "node:path";

import { loadDataConfig } from "./config";
import { createDataResources } from "./data";

/**
 * Absolute path to the single Lambda deployment artifact produced by
 * `make build`. Slice 13 wraps this in a `pulumi.asset.FileArchive`; surfacing
 * it here keeps the build/deploy contract in one obvious place.
 */
export const lambdaArtifactPath: string = path.resolve(
  __dirname,
  "..",
  "backend",
  "dist",
  "lambda.zip",
);

const data = createDataResources(loadDataConfig());

// Stack outputs consumed by slice 13 (compute/CDN) — the table to grant the
// Lambda, and the two bucket identities (the public bucket's regional domain is
// the CloudFront OAC origin).
export const tableName = data.table.name;
export const tableArn = data.table.arn;
export const privateBucketName = data.privateBucket.bucket;
export const privateBucketArn = data.privateBucket.arn;
export const publicBucketName = data.publicBucket.bucket;
export const publicBucketArn = data.publicBucket.arn;
export const publicBucketRegionalDomainName =
  data.publicBucket.bucketRegionalDomainName;
