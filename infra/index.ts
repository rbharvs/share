/**
 * Pulumi entrypoint for the `share` infrastructure (AWS + Cloudflare).
 *
 * Slice 11 only scaffolds this workspace so later slices have a home and CI can
 * typecheck it. The empty stack is filled in by:
 *   - slice 12: DynamoDB metadata table + private/public S3 buckets
 *   - slice 13: Lambda + API Gateway (REST) + CloudFront/OAC + ACM
 *   - slice 14: Cloudflare DNS records + Access apps/policies + deploy wiring
 *
 * The Lambda is deployed from the PREBUILT zip emitted by `make build`
 * (`backend/dist/lambda.zip`). Pulumi treats it as an opaque input — no frontend
 * build, no dependency vendoring, and no Docker happen during `pulumi preview`.
 */

import * as path from "node:path";

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
