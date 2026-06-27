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

import * as pulumi from "@pulumi/pulumi";

import { loadDataConfig, loadEdgeConfig } from "./config";
import { createCdnResources } from "./cdn";
import { createComputeResources } from "./compute";
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
const edgeConfig = loadEdgeConfig();

// CDN first: the public distribution only needs the (private) public bucket, and
// the compute layer needs the distribution id/arn (Lambda env + invalidation
// IAM). data -> cdn -> compute, no cycle.
const cdn = createCdnResources({
  cfg: edgeConfig,
  provider: data.provider,
  publicBucket: data.publicBucket,
});

const compute = createComputeResources({
  cfg: edgeConfig,
  provider: data.provider,
  // Pulumi treats the prebuilt zip as an opaque input — no build at preview.
  code: new pulumi.asset.FileArchive(lambdaArtifactPath),
  tableName: data.table.name,
  tableArn: data.table.arn,
  privateBucket: data.privateBucket.bucket,
  privateBucketArn: data.privateBucket.arn,
  publicBucket: data.publicBucket.bucket,
  publicBucketArn: data.publicBucket.arn,
  distributionId: cdn.distribution.id,
  distributionArn: cdn.distribution.arn,
});

// --- Data-layer stack outputs ---------------------------------------------
export const tableName = data.table.name;
export const tableArn = data.table.arn;
export const privateBucketName = data.privateBucket.bucket;
export const privateBucketArn = data.privateBucket.arn;
export const publicBucketName = data.publicBucket.bucket;
export const publicBucketArn = data.publicBucket.arn;
export const publicBucketRegionalDomainName =
  data.publicBucket.bucketRegionalDomainName;

// --- Compute + CDN stack outputs (consumed by slice 14 Cloudflare wiring) --
export const lambdaName = compute.lambda.name;
export const lambdaArn = compute.lambda.arn;
export const restApiId = compute.restApi.id;
/** Regional API Gateway domains the private hosts CNAME to (slice 14 DNS). */
export const apiRegionalDomainNames = compute.customDomains.map(
  (d) => d.regionalDomainName,
);
/** The public host's CloudFront domain (slice 14 DNS-only record target). */
export const cloudFrontDomainName = cdn.distribution.domainName;
export const cloudFrontDistributionId = cdn.distribution.id;
