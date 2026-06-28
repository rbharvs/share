/**
 * Focused config checks for the slice-13 compute layer, run under Pulumi's
 * unit-test mocks (no AWS, no `pulumi up`). These assert the security/PRD
 * invariants `pulumi preview` alone would not catch: the Lambda runtime
 * contract, the Cloudflare-only API Gateway resource policy, access logging +
 * 30-day retention, and regional custom domains for both private hosts.
 */

import * as aws from "@pulumi/aws";
import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";
import { expect } from "chai";

import { CLOUDFLARE_IP_RANGES } from "../cloudflareIps";
import type { EdgeConfig } from "../config";
import {
  ACCESS_LOG_FORMAT,
  LAMBDA_ARCHITECTURE,
  LAMBDA_RUNTIME,
  buildResourcePolicy,
  createComputeResources,
  type ComputeResources,
} from "../compute";

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

const DISTRIBUTION_ID = "E1ABCDEFG2345";

describe("compute layer", () => {
  let compute: ComputeResources;

  before(() => {
    pulumi.runtime.setMocks(
      {
        newResource: (args: pulumi.runtime.MockResourceArgs) => ({
          id: `${args.name}-id`,
          // Synthesize an `arn` so computed cross-resource references (access-log
          // destination, account CloudWatch role) resolve to a string here; ACM
          // certs also need the computed domainValidationOptions so the DNS
          // validation chain resolves under the mock.
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
    compute = createComputeResources({
      cfg: CFG,
      provider,
      // Synthetic in-memory archive: no built zip needed under mocks.
      code: new pulumi.asset.AssetArchive({
        "handler.py": new pulumi.asset.StringAsset("# stub"),
      }),
      tableName: "share",
      tableArn: "arn:aws:dynamodb:us-east-1:111122223333:table/share",
      privateBucket: "share-private",
      privateBucketArn: "arn:aws:s3:::share-private",
      publicBucket: "share-public",
      publicBucketArn: "arn:aws:s3:::share-public",
      distributionId: DISTRIBUTION_ID,
      distributionArn: `arn:aws:cloudfront::111122223333:distribution/${DISTRIBUTION_ID}`,
      // AccessConfig mirroring (slice 14): production issuer + per-host AUDs.
      accessIssuer: "https://myteam.cloudflareaccess.com",
      accessJwksUrl:
        "https://myteam.cloudflareaccess.com/cdn-cgi/access/certs",
      dashboardAudience: "dashboard-aud-tag",
      privateAudience: "private-aud-tag",
      ownerEmail: "owner@example.com",
      cloudflareProvider: new cloudflare.Provider("cf", {
        apiToken: "test-token",
      }),
      dashboardZoneId: "test-dashboard-zone",
      contentZoneId: "test-content-zone",
    });
  });

  describe("Lambda", () => {
    it("uses the PRD runtime contract (py3.12 / arm64 / 512 MB / 30 s)", async () => {
      expect(await promiseOf(compute.lambda.runtime)).to.equal(LAMBDA_RUNTIME);
      expect(LAMBDA_RUNTIME).to.equal("python3.12");
      expect(await promiseOf(compute.lambda.architectures)).to.deep.equal([
        LAMBDA_ARCHITECTURE,
      ]);
      expect(LAMBDA_ARCHITECTURE).to.equal("arm64");
      expect(await promiseOf(compute.lambda.memorySize)).to.equal(512);
      expect(await promiseOf(compute.lambda.timeout)).to.equal(30);
    });

    it("invokes the Mangum handler entrypoint", async () => {
      expect(await promiseOf(compute.lambda.handler)).to.equal(
        "share.handler.handler",
      );
    });

    it("passes the distribution id + resource names through the environment", async () => {
      const env = await promiseOf(compute.lambda.environment);
      const vars = env?.variables ?? {};
      expect(vars.SHARE_CLOUDFRONT_DISTRIBUTION_ID).to.equal(DISTRIBUTION_ID);
      expect(vars.SHARE_TABLE_NAME).to.equal("share");
      expect(vars.SHARE_PRIVATE_BUCKET).to.equal("share-private");
      expect(vars.SHARE_PUBLIC_BUCKET).to.equal("share-public");
      // Owner allowlist injected from config (never the generic settings.py default).
      expect(vars.SHARE_ALLOWED_OWNER_EMAIL).to.equal("owner@example.com");
    });

    it("mirrors the Cloudflare Access issuer + per-host AUDs into the env", async () => {
      const env = await promiseOf(compute.lambda.environment);
      const vars = env?.variables ?? {};
      // These map onto backend Settings.access_issuer / *_audience / jwks_url,
      // which access_configs() reads per host. The two AUDs stay DISTINCT (the
      // cross-host replay defense) and the issuer is the real cloudflareaccess
      // domain — never the localhost dev issuer.
      expect(vars.SHARE_ACCESS_ISSUER).to.equal(
        "https://myteam.cloudflareaccess.com",
      );
      expect(vars.SHARE_JWKS_URL).to.equal(
        "https://myteam.cloudflareaccess.com/cdn-cgi/access/certs",
      );
      expect(vars.SHARE_DASHBOARD_AUDIENCE).to.equal("dashboard-aud-tag");
      expect(vars.SHARE_PRIVATE_AUDIENCE).to.equal("private-aud-tag");
      expect(vars.SHARE_DASHBOARD_AUDIENCE).to.not.equal(
        vars.SHARE_PRIVATE_AUDIENCE,
      );
    });

    it("retains the Lambda log group for 30 days", async () => {
      expect(await promiseOf(compute.lambdaLogGroup.retentionInDays)).to.equal(
        30,
      );
      expect(await promiseOf(compute.lambdaLogGroup.name)).to.match(
        /^\/aws\/lambda\//,
      );
    });
  });

  describe("IAM naming", () => {
    // The share-deploy identity can only manage role/share-* and policy/share-*,
    // so every IAM role's physical name MUST start with "share-" or the deploy
    // fails with AccessDenied. Pulumi auto-naming would NOT add that prefix.
    it("gives the Lambda execution role a share- name prefix", async () => {
      const prefix = await promiseOf(
        compute.role.namePrefix as pulumi.Output<string>,
      );
      expect(prefix).to.be.a("string").and.match(/^share-/);
    });
  });

  describe("API Gateway", () => {
    it("is a REGIONAL REST API", async () => {
      const endpoint = await promiseOf(compute.restApi.endpointConfiguration);
      expect(endpoint?.types).to.equal("REGIONAL");
    });

    it("restricts invoke to the checked-in Cloudflare IP ranges", async () => {
      const raw = await promiseOf(compute.restApi.policy);
      const policy = JSON.parse(raw as string);
      const deny = policy.Statement.find(
        (s: { Effect: string }) => s.Effect === "Deny",
      );
      expect(deny, "a Deny statement must exist").to.exist;
      const allowed = deny.Condition.NotIpAddress["aws:SourceIp"];
      expect(allowed).to.deep.equal([...CLOUDFLARE_IP_RANGES]);
      expect(allowed).to.not.include("0.0.0.0/0");
    });

    it("enables access logging to a 30-day log group", async () => {
      const settings = await promiseOf(compute.stage.accessLogSettings);
      expect(settings?.destinationArn).to.be.a("string").and.not.empty;
      expect(settings?.format).to.equal(ACCESS_LOG_FORMAT);
      expect(await promiseOf(compute.accessLogGroup.retentionInDays)).to.equal(
        30,
      );
    });

    it("provisions a CloudWatch role at the account level for logging", async () => {
      expect(
        await promiseOf(compute.apiGatewayAccount.cloudwatchRoleArn),
      ).to.be.a("string").and.not.empty;
    });
  });

  describe("custom domains", () => {
    it("creates a regional domain for each private host", async () => {
      expect(compute.customDomains).to.have.length(2);
      const names = await Promise.all(
        compute.customDomains.map((d) => promiseOf(d.domainName)),
      );
      expect(new Set(names)).to.deep.equal(
        new Set(["share.example.com", "private.usercontent.example"]),
      );
      for (const domain of compute.customDomains) {
        const endpoint = await promiseOf(domain.endpointConfiguration);
        expect(endpoint?.types).to.equal("REGIONAL");
      }
    });

    it("backs each domain with a DNS-validated ACM cert", async () => {
      expect(compute.certificates).to.have.length(2);
      for (const cert of compute.certificates) {
        expect(await promiseOf(cert.validationMethod)).to.equal("DNS");
      }
      const certHosts = await Promise.all(
        compute.certificates.map((c) => promiseOf(c.domainName)),
      );
      expect(new Set(certHosts)).to.deep.equal(
        new Set(["share.example.com", "private.usercontent.example"]),
      );
    });
  });

  describe("resource policy builder", () => {
    it("denies any source IP outside the supplied ranges", () => {
      const policy = buildResourcePolicy(["203.0.113.0/24"]) as {
        Statement: Array<{
          Effect: string;
          Condition?: { NotIpAddress?: { "aws:SourceIp": string[] } };
        }>;
      };
      const deny = policy.Statement.find((s) => s.Effect === "Deny");
      expect(deny?.Condition?.NotIpAddress?.["aws:SourceIp"]).to.deep.equal([
        "203.0.113.0/24",
      ]);
    });

    it("defaults to every checked-in Cloudflare range", () => {
      const policy = buildResourcePolicy() as {
        Statement: Array<{
          Effect: string;
          Condition?: { NotIpAddress?: { "aws:SourceIp": string[] } };
        }>;
      };
      const deny = policy.Statement.find((s) => s.Effect === "Deny");
      expect(deny?.Condition?.NotIpAddress?.["aws:SourceIp"]).to.have.members([
        ...CLOUDFLARE_IP_RANGES,
      ]);
    });
  });
});
