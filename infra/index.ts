/**
 * Pulumi entrypoint for the `share` infrastructure (AWS + Cloudflare).
 *
 * The full stack, built data -> cdn -> access -> compute -> dns:
 *   - slice 12: DynamoDB single table + private and public S3 buckets
 *   - slice 13: Lambda + API Gateway (REST) + CloudFront/OAC + ACM
 *   - slice 14: Cloudflare Access apps (whose AUDs feed the Lambda env) +
 *     Cloudflare DNS records (private hosts proxied, public host DNS-only)
 *
 * The Lambda is deployed from the PREBUILT zip emitted by `make build`
 * (`backend/dist/lambda.zip`). Pulumi treats it as an opaque input — no frontend
 * build, no dependency vendoring, and no Docker happen during `pulumi preview`.
 */

import * as path from "node:path";

import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";

import {
  loadCloudflareConfig,
  loadDataConfig,
  loadEdgeConfig,
} from "./config";
import { createCdnResources } from "./cdn";
import {
  createCloudflareAccess,
  createCloudflareDns,
} from "./cloudflare";
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
const cloudflareConfig = loadCloudflareConfig();

// Cloudflare provider: the API token is a stack secret (falls back to the
// CLOUDFLARE_API_TOKEN env var if unset). Created first because the CDN + compute
// layers now lay their ACM DNS-validation records into Cloudflare.
const cloudflareProvider = new cloudflare.Provider("cloudflare", {
  apiToken: new pulumi.Config("share").getSecret("cloudflareApiToken"),
});

// CDN first: the public distribution only needs the (private) public bucket, and
// the compute layer needs the distribution id/arn (Lambda env + invalidation
// IAM). data -> cdn -> compute, no cycle.
const cdn = createCdnResources({
  cfg: edgeConfig,
  provider: data.provider,
  publicBucket: data.publicBucket,
  cloudflareProvider,
  publicZoneId: cloudflareConfig.contentZoneId,
});

// Access apps have no AWS dependency, and the compute Lambda must learn their
// generated AUD tags (the AccessConfig mirroring). So: access -> compute -> dns.
const access = createCloudflareAccess({
  cfg: cloudflareConfig,
  provider: cloudflareProvider,
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
  // AccessConfig mirroring: the live Cloudflare issuer + per-host AUDs flow
  // straight into the Lambda env, so the verifier can never drift from the apps.
  accessIssuer: access.issuer,
  accessJwksUrl: access.jwksUrl,
  dashboardAudience: access.dashboardAudience,
  privateAudience: access.privateAudience,
  ownerEmail: cloudflareConfig.allowedOwnerEmail,
  // ACM DNS validation lands in the matching Cloudflare zone per host apex.
  cloudflareProvider,
  dashboardZoneId: cloudflareConfig.dashboardZoneId,
  contentZoneId: cloudflareConfig.contentZoneId,
});

// DNS last: the private records target the API Gateway regional domains (built
// in compute, ordered [dashboard, private]); the public record targets CloudFront.
const dns = createCloudflareDns({
  cfg: cloudflareConfig,
  provider: cloudflareProvider,
  dashboardApiTarget: compute.customDomains[0].regionalDomainName,
  privateApiTarget: compute.customDomains[1].regionalDomainName,
  publicCloudFrontDomain: cdn.distribution.domainName,
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

// --- Cloudflare stack outputs ----------------------------------------------
// The Access issuer + per-host AUDs are the single source of truth the backend
// verifier mirrors; they are wired straight into the Lambda env above and also
// surfaced here for the deploy runbook / out-of-band verification.
export const accessIssuer = access.issuer;
export const accessJwksUrl = access.jwksUrl;
export const dashboardAudience = access.dashboardAudience;
export const privateAudience = access.privateAudience;
export const dashboardDnsName = dns.dashboardRecord.name;
export const privateDnsName = dns.privateRecord.name;
export const publicDnsName = dns.publicRecord.name;
