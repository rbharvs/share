/**
 * Focused config checks for the slice-12 data layer.
 *
 * These run the resource program under Pulumi's unit-test mocks (no AWS calls,
 * no `pulumi up`) and assert the security/PRD invariants that `pulumi preview`
 * alone would not catch. They are the "infra config checks" the slice-12
 * acceptance criteria require alongside typecheck + preview.
 */

import * as pulumi from "@pulumi/pulumi";
import { expect } from "chai";

import { DATA_DEFAULTS, type DataConfig } from "../config";
import {
  TABLE_HASH_KEY,
  TABLE_RANGE_KEY,
  TMP_LIFECYCLE_RULE_ID,
  TMP_PREFIX,
  createDataResources,
  type DataResources,
} from "../data";

/** Resolve an Output<T> to its underlying value within the mock runtime. */
function promiseOf<T>(output: pulumi.Output<T>): Promise<T> {
  return new Promise((resolve) => output.apply(resolve));
}

const TEST_CONFIG: DataConfig = {
  region: "us-east-1",
  tableName: "share",
  ttlAttribute: "expires_at_epoch",
  privateBucket: "share-private",
  publicBucket: "share-public",
  dashboardOrigins: ["https://share.example.com"],
  tmpExpirationDays: 1,
};

describe("data layer", () => {
  let data: DataResources;

  before(() => {
    pulumi.runtime.setMocks(
      {
        newResource: (args: pulumi.runtime.MockResourceArgs) => ({
          id: `${args.name}-id`,
          state: args.inputs,
        }),
        call: (args: pulumi.runtime.MockCallArgs) => args.inputs,
      },
      "share",
      "test",
    );
    data = createDataResources(TEST_CONFIG);
  });

  describe("DynamoDB single table", () => {
    it("uses PAY_PER_REQUEST with the pk/sk single-table keys", async () => {
      expect(await promiseOf(data.table.name)).to.equal("share");
      expect(await promiseOf(data.table.billingMode)).to.equal(
        "PAY_PER_REQUEST",
      );
      expect(await promiseOf(data.table.hashKey)).to.equal(TABLE_HASH_KEY);
      expect(await promiseOf(data.table.rangeKey)).to.equal(TABLE_RANGE_KEY);

      const attributes = await promiseOf(data.table.attributes);
      expect(attributes).to.have.deep.members([
        { name: "pk", type: "S" },
        { name: "sk", type: "S" },
      ]);
    });

    it("enables point-in-time recovery", async () => {
      const pitr = await promiseOf(data.table.pointInTimeRecovery);
      expect(pitr?.enabled).to.equal(true);
    });

    it("enables TTL on the upload-session expiry attribute", async () => {
      const ttl = await promiseOf(data.table.ttl);
      expect(ttl?.enabled).to.equal(true);
      expect(ttl?.attributeName).to.equal("expires_at_epoch");
    });
  });

  describe("S3 buckets", () => {
    it("creates two separate, distinctly-named buckets", async () => {
      const privateName = await promiseOf(data.privateBucket.bucket);
      const publicName = await promiseOf(data.publicBucket.bucket);
      expect(privateName).to.equal("share-private");
      expect(publicName).to.equal("share-public");
      expect(privateName).to.not.equal(publicName);
    });

    it("applies default server-side encryption to both buckets", async () => {
      for (const sse of [data.privateBucketSse, data.publicBucketSse]) {
        const rules = (await promiseOf(sse.rules)) ?? [];
        expect(rules).to.have.length(1);
        expect(
          rules[0].applyServerSideEncryptionByDefault?.sseAlgorithm,
        ).to.equal("AES256");
      }
    });

    it("leaves both buckets unversioned", async () => {
      for (const v of [
        data.privateBucketVersioning,
        data.publicBucketVersioning,
      ]) {
        const cfg = await promiseOf(v.versioningConfiguration);
        expect(cfg.status).to.equal("Disabled");
      }
    });
  });

  describe("private bucket lifecycle", () => {
    it("expires only tmp/ after ~1 day, leaving raw/ and artifacts/", async () => {
      const rules = (await promiseOf(data.privateBucketLifecycle.rules)) ?? [];
      expect(rules).to.have.length(1);

      const rule = rules[0];
      expect(rule.id).to.equal(TMP_LIFECYCLE_RULE_ID);
      expect(rule.status).to.equal("Enabled");
      expect(rule.filter?.prefix).to.equal(TMP_PREFIX);
      expect(rule.expiration?.days).to.equal(1);

      // No rule may ever target the immutable raw/ or artifacts/ prefixes.
      for (const r of rules) {
        expect(r.filter?.prefix).to.not.match(/^(raw|artifacts)\//);
      }
    });
  });

  describe("private bucket CORS", () => {
    it("allows only the dashboard origin(s) and POST", async () => {
      const corsRules = (await promiseOf(data.privateBucketCors.corsRules)) ?? [];
      expect(corsRules).to.have.length(1);

      const rule = corsRules[0];
      expect(rule.allowedMethods).to.deep.equal(["POST"]);
      expect(rule.allowedOrigins).to.deep.equal([
        "https://share.example.com",
      ]);
      // Defense-in-depth: never a wildcard origin on the upload surface.
      expect(rule.allowedOrigins).to.not.include("*");
    });
  });

  describe("public access blocking", () => {
    it("blocks all public access on both buckets (public bucket = OAC-only)", async () => {
      for (const block of [
        data.privateBucketAccessBlock,
        data.publicBucketAccessBlock,
      ]) {
        expect(await promiseOf(block.blockPublicAcls)).to.equal(true);
        expect(await promiseOf(block.blockPublicPolicy)).to.equal(true);
        expect(await promiseOf(block.ignorePublicAcls)).to.equal(true);
        expect(await promiseOf(block.restrictPublicBuckets)).to.equal(true);
      }
    });
  });

  describe("naming defaults mirror the backend settings provider", () => {
    it("matches backend table_name / private_bucket / public_bucket", () => {
      expect(DATA_DEFAULTS.tableName).to.equal("share");
      expect(DATA_DEFAULTS.privateBucket).to.equal("share-private");
      expect(DATA_DEFAULTS.publicBucket).to.equal("share-public");
      expect(DATA_DEFAULTS.ttlAttribute).to.equal("expires_at_epoch");
    });
  });
});
