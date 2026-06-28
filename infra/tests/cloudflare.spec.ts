/**
 * Focused config checks for the slice-14 Cloudflare layer, run under Pulumi's
 * unit-test mocks (no Cloudflare, no `pulumi up`). These assert the security/PRD
 * invariants `pulumi preview` alone would not catch: proxied private hosts vs. a
 * DNS-only public host, two SEPARATE Access apps with DISTINCT audiences, a
 * 7-day session, an owner-only allow policy, and the derived (never-localhost)
 * issuer/JWKS the backend verifier mirrors.
 */

import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";
import { expect } from "chai";

import type { CloudflareConfig } from "../config";
import {
  ACCESS_APP_TYPE,
  CNAME,
  DNS_ONLY_TTL,
  PROXIED_TTL,
  SESSION_DURATION_7_DAYS,
  accessIssuer,
  accessJwksUrl,
  createCloudflareAccess,
  createCloudflareDns,
  type CloudflareAccessResources,
  type CloudflareDnsResources,
} from "../cloudflare";

function promiseOf<T>(output: pulumi.Output<T>): Promise<T> {
  return new Promise((resolve) => output.apply(resolve));
}

const CFG: CloudflareConfig = {
  accountId: "acct-123",
  dashboardZoneId: "zone-dashboard",
  contentZoneId: "zone-content",
  dashboardHost: "share.example.com",
  privateHost: "private.usercontent.example",
  publicHost: "public.usercontent.example",
  allowedOwnerEmail: "owner@example.com",
  teamDomain: "myteam",
  sessionDuration: SESSION_DURATION_7_DAYS,
};

describe("cloudflare layer", () => {
  before(() => {
    pulumi.runtime.setMocks(
      {
        newResource: (args: pulumi.runtime.MockResourceArgs) => ({
          id: `${args.name}-id`,
          // Synthesize a per-resource `aud` so the two Access apps resolve to
          // DISTINCT audience tags (Cloudflare generates these server-side).
          state: { aud: `${args.name}-aud`, ...args.inputs },
        }),
        call: (args: pulumi.runtime.MockCallArgs) => args.inputs,
      },
      "share",
      "test",
    );
  });

  describe("issuer/JWKS derivation", () => {
    it("derives the cloudflareaccess issuer from the team domain", () => {
      expect(accessIssuer("myteam")).to.equal("https://myteam.cloudflareaccess.com");
    });

    it("appends the Access certs path for the JWKS url", () => {
      expect(accessJwksUrl(accessIssuer("myteam"))).to.equal(
        "https://myteam.cloudflareaccess.com/cdn-cgi/access/certs",
      );
    });

    it("never derives a localhost issuer (prod config only)", () => {
      const issuer = accessIssuer(CFG.teamDomain);
      expect(issuer).to.match(/^https:\/\/[^/]+\.cloudflareaccess\.com$/);
      expect(issuer).to.not.contain("localhost");
    });
  });

  describe("Access applications", () => {
    let access: CloudflareAccessResources;

    before(() => {
      const provider = new cloudflare.Provider("cloudflare", {});
      access = createCloudflareAccess({ cfg: CFG, provider });
    });

    it("creates two SEPARATE self-hosted apps, one per private host", async () => {
      const dashType = await promiseOf(access.dashboardApp.type);
      const privType = await promiseOf(access.privateApp.type);
      expect(dashType).to.equal(ACCESS_APP_TYPE);
      expect(privType).to.equal(ACCESS_APP_TYPE);
      expect(ACCESS_APP_TYPE).to.equal("self_hosted");

      const dashDomain = await promiseOf(access.dashboardApp.domain);
      const privDomain = await promiseOf(access.privateApp.domain);
      expect(dashDomain).to.equal("share.example.com");
      expect(privDomain).to.equal("private.usercontent.example");
    });

    it("gives the two apps DISTINCT audiences (cross-host replay defense)", async () => {
      const dashAud = await promiseOf(access.dashboardAudience);
      const privAud = await promiseOf(access.privateAudience);
      expect(dashAud).to.be.a("string").and.not.empty;
      expect(privAud).to.be.a("string").and.not.empty;
      expect(dashAud).to.not.equal(privAud);
    });

    it("uses a 7-day session on both apps", async () => {
      expect(await promiseOf(access.dashboardApp.sessionDuration)).to.equal("168h");
      expect(await promiseOf(access.privateApp.sessionDuration)).to.equal("168h");
      expect(SESSION_DURATION_7_DAYS).to.equal("168h");
    });

    it("attaches an owner-only allow policy (plain email allowlist)", async () => {
      for (const policy of [access.dashboardPolicy, access.privatePolicy]) {
        expect(await promiseOf(policy.decision)).to.equal("allow");
        const includes = await promiseOf(policy.includes);
        expect(includes?.[0]?.email?.email).to.equal("owner@example.com");
      }
    });

    it("surfaces the derived issuer + JWKS for the verifier to mirror", () => {
      expect(access.issuer).to.equal("https://myteam.cloudflareaccess.com");
      expect(access.jwksUrl).to.equal("https://myteam.cloudflareaccess.com/cdn-cgi/access/certs");
    });
  });

  describe("DNS records", () => {
    let dns: CloudflareDnsResources;

    before(() => {
      const provider = new cloudflare.Provider("cloudflare", {});
      dns = createCloudflareDns({
        cfg: CFG,
        provider,
        dashboardApiTarget: "d-abc.execute-api.us-east-1.amazonaws.com",
        privateApiTarget: "d-def.execute-api.us-east-1.amazonaws.com",
        publicCloudFrontDomain: "d111.cloudfront.net",
      });
    });

    it("proxies both private hosts (forces ingress through Cloudflare)", async () => {
      expect(await promiseOf(dns.dashboardRecord.proxied)).to.equal(true);
      expect(await promiseOf(dns.privateRecord.proxied)).to.equal(true);
      // Proxied records must use Cloudflare's automatic TTL.
      expect(await promiseOf(dns.dashboardRecord.ttl)).to.equal(PROXIED_TTL);
      expect(await promiseOf(dns.privateRecord.ttl)).to.equal(PROXIED_TTL);
    });

    it("keeps the public host DNS-only to CloudFront (never hits Lambda)", async () => {
      expect(await promiseOf(dns.publicRecord.proxied)).to.equal(false);
      expect(await promiseOf(dns.publicRecord.ttl)).to.equal(DNS_ONLY_TTL);
      expect(await promiseOf(dns.publicRecord.content)).to.equal("d111.cloudfront.net");
    });

    it("places each record in the correct zone as a CNAME", async () => {
      expect(await promiseOf(dns.dashboardRecord.zoneId)).to.equal("zone-dashboard");
      expect(await promiseOf(dns.privateRecord.zoneId)).to.equal("zone-content");
      expect(await promiseOf(dns.publicRecord.zoneId)).to.equal("zone-content");
      for (const record of [dns.dashboardRecord, dns.privateRecord, dns.publicRecord]) {
        expect(await promiseOf(record.type)).to.equal(CNAME);
      }
    });

    it("targets the API Gateway regional domains for the private hosts", async () => {
      expect(await promiseOf(dns.dashboardRecord.content)).to.equal(
        "d-abc.execute-api.us-east-1.amazonaws.com",
      );
      expect(await promiseOf(dns.privateRecord.content)).to.equal(
        "d-def.execute-api.us-east-1.amazonaws.com",
      );
    });
  });
});
