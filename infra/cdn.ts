/**
 * Public-content CDN: the CloudFront distribution that serves
 * `public.usercontent.example` from the (private) public S3 bucket via Origin
 * Access Control.
 *
 * Security/PRD invariants encoded here (asserted by `tests/cdn.spec.ts`):
 *
 * - The public bucket stays PRIVATE: CloudFront reaches it only through OAC
 *   (SigV4), and a bucket policy grants `s3:GetObject` solely to this
 *   distribution (`AWS:SourceArn` condition). No public ACL, no OAI.
 * - A response-headers policy emits the rendered-content security headers,
 *   reproducing {@link SHARED_SECURITY_HEADERS} byte-for-byte (CSP `sandbox`
 *   WITHOUT `allow-same-origin`, nosniff, no-referrer, noindex) plus the public
 *   `Cache-Control: public, max-age=3600`.
 * - A viewer-request CloudFront Function maps `/u/{sha}` and `/u/{sha}/` to the
 *   object's `index.html` (a rewrite, NOT a redirect) so both URL shapes load.
 * - TLS via a DNS-validated ACM certificate (us-east-1, as CloudFront requires).
 *
 * Construction is a pure function of its inputs so the focused config checks can
 * drive it under Pulumi's unit-test mocks without touching AWS.
 */

import * as aws from "@pulumi/aws";
import * as pulumi from "@pulumi/pulumi";

import type { EdgeConfig } from "./config";
import { PUBLIC_CACHE_CONTROL, SHARED_SECURITY_HEADERS } from "./securityHeaders";

/**
 * Viewer-request function source. Rewrites the request URI in place (no 30x
 * redirect) so a bare `/u/{sha}` or trailing-slash `/u/{sha}/` both resolve to
 * the SHA-addressed `index.html` object the publish step writes
 * (`u/{sha}/index.html`).
 */
export const REWRITE_FUNCTION_CODE = `function handler(event) {
  var request = event.request;
  var match = request.uri.match(/^\\/u\\/([^/]+)\\/?$/);
  if (match) {
    request.uri = '/u/' + match[1] + '/index.html';
  }
  return request;
}`;

/** Outputs consumed by the compute layer (Lambda invalidation) + config checks. */
export interface CdnResources {
  readonly oac: aws.cloudfront.OriginAccessControl;
  readonly responseHeadersPolicy: aws.cloudfront.ResponseHeadersPolicy;
  readonly rewriteFunction: aws.cloudfront.Function;
  readonly certificate: aws.acm.Certificate;
  readonly distribution: aws.cloudfront.Distribution;
  readonly bucketPolicy: aws.s3.BucketPolicy;
}

/** Inputs: the shared provider + the (private) public bucket from the data layer. */
export interface CdnInputs {
  readonly cfg: EdgeConfig;
  readonly provider: aws.Provider;
  readonly publicBucket: aws.s3.BucketV2;
}

/**
 * Build the CloudFront response-headers `customHeadersConfig` items from the
 * shared security headers + the public cache directive. Emitting every header
 * as an explicit `override: true` custom header keeps the byte-for-byte parity
 * with the backend helper trivially assertable.
 */
function customHeaderItems(): aws.types.input.cloudfront.ResponseHeadersPolicyCustomHeadersConfigItem[] {
  const all: Record<string, string> = {
    ...SHARED_SECURITY_HEADERS,
    "Cache-Control": PUBLIC_CACHE_CONTROL,
  };
  return Object.entries(all).map(([header, value]) => ({
    header,
    value,
    override: true,
  }));
}

export function createCdnResources(inputs: CdnInputs): CdnResources {
  const { cfg, provider, publicBucket } = inputs;
  const opts: pulumi.CustomResourceOptions = { provider };

  // OAC: CloudFront signs origin requests with SigV4 so the bucket can stay
  // private (no public ACL, no legacy OAI).
  const oac = new aws.cloudfront.OriginAccessControl(
    "public-oac",
    {
      description: "OAC for the public content bucket",
      originAccessControlOriginType: "s3",
      signingBehavior: "always",
      signingProtocol: "sigv4",
    },
    opts,
  );

  const responseHeadersPolicy = new aws.cloudfront.ResponseHeadersPolicy(
    "public-security-headers",
    {
      comment: "Rendered-content security headers (mirrors the private helper)",
      customHeadersConfig: { items: customHeaderItems() },
    },
    opts,
  );

  const rewriteFunction = new aws.cloudfront.Function(
    "public-rewrite",
    {
      runtime: "cloudfront-js-2.0",
      comment: "Map /u/{sha} and /u/{sha}/ to the object index.html",
      publish: true,
      code: REWRITE_FUNCTION_CODE,
    },
    opts,
  );

  // DNS-validated cert for the public alias. CloudFront requires us-east-1,
  // which is the stack region. The Cloudflare validation records land in
  // slice 14 (which consumes `domainValidationOptions`).
  const certificate = new aws.acm.Certificate(
    "public-cert",
    {
      domainName: cfg.publicHost,
      validationMethod: "DNS",
    },
    opts,
  );

  const distribution = new aws.cloudfront.Distribution(
    "public",
    {
      enabled: true,
      isIpv6Enabled: true,
      comment: `share public content (${cfg.publicHost})`,
      aliases: [cfg.publicHost],
      httpVersion: "http2and3",
      priceClass: "PriceClass_100",
      origins: [
        {
          originId: "public-s3-oac",
          domainName: publicBucket.bucketRegionalDomainName,
          originAccessControlId: oac.id,
        },
      ],
      defaultCacheBehavior: {
        targetOriginId: "public-s3-oac",
        viewerProtocolPolicy: "redirect-to-https",
        allowedMethods: ["GET", "HEAD", "OPTIONS"],
        cachedMethods: ["GET", "HEAD"],
        compress: true,
        // AWS managed "CachingOptimized" policy id (cache-key/TTL behaviour);
        // our own response-headers policy supplies the security headers.
        cachePolicyId: "658327ea-f89d-4fab-a63d-7e88639e58f6",
        responseHeadersPolicyId: responseHeadersPolicy.id,
        functionAssociations: [
          { eventType: "viewer-request", functionArn: rewriteFunction.arn },
        ],
      },
      restrictions: {
        geoRestriction: { restrictionType: "none" },
      },
      viewerCertificate: {
        acmCertificateArn: certificate.arn,
        sslSupportMethod: "sni-only",
        minimumProtocolVersion: "TLSv1.2_2021",
      },
    },
    opts,
  );

  // Grant ONLY this distribution read access to the (otherwise private) bucket.
  const bucketPolicy = new aws.s3.BucketPolicy(
    "public-oac-policy",
    {
      bucket: publicBucket.id,
      policy: pulumi
        .all([publicBucket.arn, distribution.arn])
        .apply(([bucketArn, distributionArn]) =>
          JSON.stringify({
            Version: "2012-10-17",
            Statement: [
              {
                Sid: "AllowCloudFrontServicePrincipalReadOnly",
                Effect: "Allow",
                Principal: { Service: "cloudfront.amazonaws.com" },
                Action: "s3:GetObject",
                Resource: `${bucketArn}/*`,
                Condition: {
                  StringEquals: { "AWS:SourceArn": distributionArn },
                },
              },
            ],
          }),
        ),
    },
    opts,
  );

  return {
    oac,
    responseHeadersPolicy,
    rewriteFunction,
    certificate,
    distribution,
    bucketPolicy,
  };
}
