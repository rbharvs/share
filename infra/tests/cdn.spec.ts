/**
 * Focused config checks for the slice-13 public CDN layer, run under Pulumi's
 * unit-test mocks (no AWS, no `pulumi up`). These assert the security/PRD
 * invariants `pulumi preview` alone would not catch: OAC-only origin access, the
 * byte-for-byte rendered-content security headers, the in-place slash/no-slash
 * rewrite, and the distribution-scoped bucket policy.
 */

import * as aws from "@pulumi/aws";
import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";
import { expect } from "chai";

import type { EdgeConfig } from "../config";
import { REWRITE_FUNCTION_CODE, createCdnResources, type CdnResources } from "../cdn";
import { publicResponseHeaders } from "../securityHeaders";

function promiseOf<T>(output: pulumi.Output<T>): Promise<T> {
  return new Promise((resolve) => output.apply(resolve));
}

const CFG: EdgeConfig = {
  region: "us-east-1",
  dashboardHost: "share.example.com",
  privateHost: "private.usercontent.example",
  publicHost: "public.usercontent.example",
  lambdaMemoryMb: 512,
  lambdaTimeoutSeconds: 30,
  lambdaHandler: "share.handler.handler",
  logRetentionDays: 30,
};

/** Evaluate the CloudFront viewer-request function and return its handler. */
function loadRewriteHandler(): (event: { request: { uri: string } }) => {
  uri: string;
} {
  return new Function(`${REWRITE_FUNCTION_CODE}\nreturn handler;`)() as (event: {
    request: { uri: string };
  }) => { uri: string };
}

describe("public CDN layer", () => {
  let cdn: CdnResources;

  before(() => {
    pulumi.runtime.setMocks(
      {
        newResource: (args: pulumi.runtime.MockResourceArgs) => ({
          id: `${args.name}-id`,
          // Synthesize an `arn` so cross-resource references (e.g. the bucket
          // policy's `AWS:SourceArn`) resolve to a string under the mock; ACM
          // certs also need the computed domainValidationOptions so the DNS
          // validation chain resolves.
          state: {
            arn: `arn:aws:test:::${args.name}`,
            ...(args.type === "aws:acm/certificate:Certificate"
              ? {
                  domainValidationOptions: [
                    {
                      resourceRecordName: `_val.${args.inputs.domainName}.`,
                      resourceRecordType: "CNAME",
                      resourceRecordValue: "_v.acm-validations.aws.",
                    },
                  ],
                }
              : {}),
            ...args.inputs,
          },
        }),
        call: (args: pulumi.runtime.MockCallArgs) => args.inputs,
      },
      "share",
      "test",
    );
    const provider = new aws.Provider("aws", { region: "us-east-1" });
    const cloudflareProvider = new cloudflare.Provider("cf", {
      apiToken: "test-token",
    });
    const publicBucket = new aws.s3.BucketV2("public", { bucket: "share-public" }, { provider });
    cdn = createCdnResources({
      cfg: CFG,
      provider,
      publicBucket,
      cloudflareProvider,
      publicZoneId: "test-content-zone",
    });
  });

  describe("origin access control", () => {
    it("signs every origin request with SigV4 against S3", async () => {
      expect(await promiseOf(cdn.oac.originAccessControlOriginType)).to.equal("s3");
      expect(await promiseOf(cdn.oac.signingBehavior)).to.equal("always");
      expect(await promiseOf(cdn.oac.signingProtocol)).to.equal("sigv4");
    });

    it("uses OAC on the origin (no public OAI / custom origin)", async () => {
      const origins = await promiseOf(cdn.distribution.origins);
      expect(origins).to.have.length(1);
      const origin = origins[0];
      expect(origin.originAccessControlId).to.be.a("string").and.not.empty;
      expect(origin.s3OriginConfig).to.equal(undefined);
      expect(origin.customOriginConfig).to.equal(undefined);
    });
  });

  describe("distribution", () => {
    it("serves only the public host over HTTPS", async () => {
      expect(await promiseOf(cdn.distribution.aliases)).to.deep.equal([
        "public.usercontent.example",
      ]);
      const behavior = await promiseOf(cdn.distribution.defaultCacheBehavior);
      expect(behavior.viewerProtocolPolicy).to.equal("redirect-to-https");
      expect(behavior.responseHeadersPolicyId).to.be.a("string").and.not.empty;
    });

    it("attaches the rewrite function on viewer-request", async () => {
      const behavior = await promiseOf(cdn.distribution.defaultCacheBehavior);
      const assocs = behavior.functionAssociations ?? [];
      expect(assocs).to.have.length(1);
      expect(assocs[0].eventType).to.equal("viewer-request");
    });

    it("terminates TLS with a DNS-validated ACM cert for the public host", async () => {
      expect(await promiseOf(cdn.certificate.domainName)).to.equal("public.usercontent.example");
      expect(await promiseOf(cdn.certificate.validationMethod)).to.equal("DNS");
      const viewer = await promiseOf(cdn.distribution.viewerCertificate);
      expect(viewer.sslSupportMethod).to.equal("sni-only");
    });
  });

  describe("response-headers policy", () => {
    it("emits the shared security headers + public cache, byte-for-byte", async () => {
      // Recognized security headers live in the typed securityHeadersConfig
      // (CloudFront rejects them as custom headers); the rest are custom.
      const sec = await promiseOf(cdn.responseHeadersPolicy.securityHeadersConfig);
      const customCfg = await promiseOf(cdn.responseHeadersPolicy.customHeadersConfig);
      const customItems = customCfg?.items ?? [];

      const emitted: Record<string, string | undefined> = {
        "Content-Security-Policy": sec?.contentSecurityPolicy?.contentSecurityPolicy,
        "X-Content-Type-Options": sec?.contentTypeOptions ? "nosniff" : undefined,
        "Referrer-Policy": sec?.referrerPolicy?.referrerPolicy,
        ...Object.fromEntries(customItems.map((i) => [i.header, i.value])),
      };
      // Same emitted set as the backend helper, byte-for-byte.
      expect(emitted).to.deep.equal(publicResponseHeaders());

      // Every override flag is set so the origin can never weaken a header.
      expect(sec?.contentSecurityPolicy?.override).to.equal(true);
      expect(sec?.contentTypeOptions?.override).to.equal(true);
      expect(sec?.referrerPolicy?.override).to.equal(true);
      for (const item of customItems) {
        expect(item.override).to.equal(true);
      }
      // The load-bearing isolation directive must never gain same-origin.
      expect(emitted["Content-Security-Policy"]).to.not.contain("allow-same-origin");
    });
  });

  describe("rewrite function", () => {
    it("uses the cloudfront-js-2.0 runtime", async () => {
      expect(await promiseOf(cdn.rewriteFunction.runtime)).to.equal("cloudfront-js-2.0");
    });

    it("maps /u/{sha} and /u/{sha}/ to index.html (rewrite, not redirect)", () => {
      const handler = loadRewriteHandler();
      expect(handler({ request: { uri: "/u/abc123" } }).uri).to.equal("/u/abc123/index.html");
      expect(handler({ request: { uri: "/u/abc123/" } }).uri).to.equal("/u/abc123/index.html");
    });

    it("leaves already-resolved and unrelated paths untouched", () => {
      const handler = loadRewriteHandler();
      expect(handler({ request: { uri: "/u/abc123/index.html" } }).uri).to.equal(
        "/u/abc123/index.html",
      );
      expect(handler({ request: { uri: "/style.css" } }).uri).to.equal("/style.css");
    });
  });

  describe("bucket policy", () => {
    it("grants read only to CloudFront for this distribution", async () => {
      const raw = await promiseOf(cdn.bucketPolicy.policy);
      const policy = JSON.parse(raw as string);
      const stmt = policy.Statement[0];
      expect(stmt.Effect).to.equal("Allow");
      expect(stmt.Principal.Service).to.equal("cloudfront.amazonaws.com");
      expect(stmt.Action).to.equal("s3:GetObject");
      expect(stmt.Condition.StringEquals).to.have.property("AWS:SourceArn");
    });
  });
});
