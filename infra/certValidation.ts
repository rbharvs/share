/**
 * ACM DNS-validation via Cloudflare.
 *
 * Slices 13/14 create DNS-validated ACM certs but never laid down the
 * validation records or gated on issuance, so the certs sat PENDING_VALIDATION
 * and the API Gateway custom domains / CloudFront distribution could not attach
 * them. This module closes that gap: for a single-domain cert it writes the
 * validation CNAME into the owning Cloudflare zone (DNS-only, short TTL) and
 * returns an {@link aws.acm.CertificateValidation} whose `certificateArn` only
 * resolves once ACM marks the cert ISSUED.
 *
 * Consumers MUST attach the returned `certificateArn` (NOT `certificate.arn`)
 * so the domain/distribution is never created against a pending cert.
 */

import * as aws from "@pulumi/aws";
import * as cloudflare from "@pulumi/cloudflare";
import * as pulumi from "@pulumi/pulumi";

export interface CertValidationInputs {
  /** Logical-name prefix for the created resources (e.g. "dashboard"). */
  readonly name: string;
  /** The ACM certificate to validate (must use `validationMethod: "DNS"`). */
  readonly certificate: aws.acm.Certificate;
  /** Cloudflare zone id that owns the certificate's domain. */
  readonly zoneId: pulumi.Input<string>;
  /** Cloudflare provider for the validation DNS record. */
  readonly cloudflareProvider: cloudflare.Provider;
  /** AWS provider the certificate + its validation live under. */
  readonly awsProvider: aws.Provider;
}

/** ACM emits FQDNs with a trailing dot; Cloudflare records must not have one. */
function stripDot(value: string): string {
  return value.endsWith(".") ? value.slice(0, -1) : value;
}

/**
 * Write the cert's DNS-validation CNAME into Cloudflare and wait for issuance.
 * Single-domain certs expose exactly one validation option.
 */
export function validateCertificate(
  inputs: CertValidationInputs,
): aws.acm.CertificateValidation {
  const { name, certificate, zoneId, cloudflareProvider, awsProvider } = inputs;

  const option = certificate.domainValidationOptions[0];

  // Validation CNAMEs must be DNS-only (grey cloud) — proxying breaks the ACM
  // lookup — with a short TTL so re-validation is quick.
  const record = new cloudflare.DnsRecord(
    `${name}-cert-validation`,
    {
      zoneId,
      name: option.resourceRecordName.apply(stripDot),
      type: option.resourceRecordType,
      content: option.resourceRecordValue.apply(stripDot),
      proxied: false,
      ttl: 60,
    },
    { provider: cloudflareProvider },
  );

  return new aws.acm.CertificateValidation(
    `${name}-cert-issued`,
    {
      certificateArn: certificate.arn,
      validationRecordFqdns: [record.name],
    },
    { provider: awsProvider },
  );
}
