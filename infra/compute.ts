/**
 * Compute layer: the Mangum-wrapped FastAPI Lambda plus the regional API Gateway
 * REST API that fronts the two PRIVATE hosts (`share.example.com` and
 * `private.usercontent.example`).
 *
 * Security/PRD invariants encoded here (asserted by `tests/compute.spec.ts`):
 *
 * - Lambda: Python 3.12 / arm64 / 512 MB / 30 s, the `share.handler.handler`
 *   Mangum entrypoint, deployed from the PREBUILT zip (no in-Pulumi build).
 * - API Gateway: REST API v1, REGIONAL endpoint + REGIONAL custom domains for
 *   both private hosts, with a resource policy that allows `execute-api:Invoke`
 *   ONLY from the checked-in Cloudflare IP ranges (defense in depth on top of
 *   Cloudflare Access + app-level JWT).
 * - Access logs enabled; Lambda + API log groups retained 30 days.
 * - Least-privilege IAM: the function may touch only its table, its two buckets,
 *   and `cloudfront:CreateInvalidation` on its own distribution.
 *
 * Construction is a pure function of its inputs (the `code` archive is injected
 * so the config checks can run under Pulumi mocks without a built zip).
 */

import * as aws from "@pulumi/aws";
import * as pulumi from "@pulumi/pulumi";

import type { EdgeConfig } from "./config";
import { CLOUDFLARE_IP_RANGES } from "./cloudflareIps";

/** PRD-mandated Lambda runtime contract. */
export const LAMBDA_RUNTIME = "python3.12";
export const LAMBDA_ARCHITECTURE = "arm64";

/** API Gateway access-log format (JSON, one object per request). */
export const ACCESS_LOG_FORMAT = JSON.stringify({
  requestId: "$context.requestId",
  ip: "$context.identity.sourceIp",
  httpMethod: "$context.httpMethod",
  resourcePath: "$context.resourcePath",
  status: "$context.status",
  protocol: "$context.protocol",
  responseLength: "$context.responseLength",
  requestTime: "$context.requestTime",
});

/** Inputs from the data + CDN layers (the shared provider, table, buckets, CDN). */
export interface ComputeInputs {
  readonly cfg: EdgeConfig;
  readonly provider: aws.Provider;
  /** The prebuilt Lambda zip, injected so tests need no built artifact. */
  readonly code: pulumi.Input<pulumi.asset.Archive>;
  readonly tableName: pulumi.Input<string>;
  readonly tableArn: pulumi.Input<string>;
  readonly privateBucket: pulumi.Input<string>;
  readonly privateBucketArn: pulumi.Input<string>;
  readonly publicBucket: pulumi.Input<string>;
  readonly publicBucketArn: pulumi.Input<string>;
  readonly distributionId: pulumi.Input<string>;
  readonly distributionArn: pulumi.Input<string>;
  // --- Access verification mirroring (slice 14) ----------------------------
  // The production Cloudflare Access issuer + per-host AUD tags, fed straight
  // from the Cloudflare resources so the backend verifier (slice 02) can never
  // drift from the live apps. The LOCAL issuer/audiences are never set here.
  readonly accessIssuer: pulumi.Input<string>;
  readonly accessJwksUrl: pulumi.Input<string>;
  readonly dashboardAudience: pulumi.Input<string>;
  readonly privateAudience: pulumi.Input<string>;
}

export interface ComputeResources {
  readonly role: aws.iam.Role;
  readonly lambda: aws.lambda.Function;
  readonly lambdaLogGroup: aws.cloudwatch.LogGroup;
  readonly restApi: aws.apigateway.RestApi;
  readonly stage: aws.apigateway.Stage;
  readonly accessLogGroup: aws.cloudwatch.LogGroup;
  readonly apiGatewayAccount: aws.apigateway.Account;
  readonly certificates: aws.acm.Certificate[];
  readonly customDomains: aws.apigateway.DomainName[];
  readonly basePathMappings: aws.apigateway.BasePathMapping[];
}

/**
 * The API Gateway resource policy: allow `execute-api:Invoke` from anywhere, then
 * DENY it whenever the source IP is NOT one of the checked-in Cloudflare ranges.
 * Exported so the config check can assert the ranges and the deny shape.
 */
export function buildResourcePolicy(
  ranges: readonly string[] = CLOUDFLARE_IP_RANGES,
): Record<string, unknown> {
  return {
    Version: "2012-10-17",
    Statement: [
      {
        Sid: "AllowInvoke",
        Effect: "Allow",
        Principal: "*",
        Action: "execute-api:Invoke",
        Resource: "execute-api:/*",
      },
      {
        Sid: "DenyNonCloudflare",
        Effect: "Deny",
        Principal: "*",
        Action: "execute-api:Invoke",
        Resource: "execute-api:/*",
        Condition: { NotIpAddress: { "aws:SourceIp": [...ranges] } },
      },
    ],
  };
}

/** SHARE_-prefixed environment for the running Lambda (Settings source of truth). */
function lambdaEnvironment(
  inputs: ComputeInputs,
): pulumi.Input<Record<string, pulumi.Input<string>>> {
  const { cfg } = inputs;
  return {
    SHARE_REGION: cfg.region,
    SHARE_DASHBOARD_HOST: cfg.dashboardHost,
    SHARE_PRIVATE_HOST: cfg.privateHost,
    SHARE_PUBLIC_HOST: cfg.publicHost,
    SHARE_DASHBOARD_ORIGIN: `https://${cfg.dashboardHost}`,
    SHARE_TABLE_NAME: inputs.tableName,
    SHARE_PRIVATE_BUCKET: inputs.privateBucket,
    SHARE_PUBLIC_BUCKET: inputs.publicBucket,
    SHARE_CLOUDFRONT_DISTRIBUTION_ID: inputs.distributionId,
    // Access verification config mirrored from the Cloudflare apps (slice 14).
    // These map onto backend `Settings.access_issuer` / `dashboard_audience` /
    // `private_audience` / `jwks_url`, which `access_configs()` reads per host.
    SHARE_ACCESS_ISSUER: inputs.accessIssuer,
    SHARE_JWKS_URL: inputs.accessJwksUrl,
    SHARE_DASHBOARD_AUDIENCE: inputs.dashboardAudience,
    SHARE_PRIVATE_AUDIENCE: inputs.privateAudience,
  };
}

export function createComputeResources(inputs: ComputeInputs): ComputeResources {
  const { cfg, provider } = inputs;
  const opts: pulumi.CustomResourceOptions = { provider };

  // --- IAM execution role ----------------------------------------------------
  const role = new aws.iam.Role(
    "lambda-role",
    {
      // Physical name MUST start with "share-": the share-deploy identity's
      // scoped IAM permissions only cover role/share-* and policy/share-*.
      namePrefix: "share-lambda-exec-",
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "lambda.amazonaws.com" },
            Action: "sts:AssumeRole",
          },
        ],
      }),
    },
    opts,
  );

  // CloudWatch Logs for the function.
  new aws.iam.RolePolicyAttachment(
    "lambda-basic-execution",
    {
      role: role.name,
      policyArn:
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    },
    opts,
  );

  // Least-privilege access to exactly this stack's data + CDN.
  new aws.iam.RolePolicy(
    "lambda-data-access",
    {
      role: role.id,
      policy: pulumi
        .all([
          inputs.tableArn,
          inputs.privateBucketArn,
          inputs.publicBucketArn,
          inputs.distributionArn,
        ])
        .apply(([tableArn, privateArn, publicArn, distributionArn]) =>
          JSON.stringify({
            Version: "2012-10-17",
            Statement: [
              {
                Sid: "Metadata",
                Effect: "Allow",
                Action: [
                  "dynamodb:GetItem",
                  "dynamodb:PutItem",
                  "dynamodb:UpdateItem",
                  "dynamodb:DeleteItem",
                  "dynamodb:Query",
                  "dynamodb:TransactWriteItems",
                ],
                Resource: [tableArn, `${tableArn}/index/*`],
              },
              {
                Sid: "PrivateBucket",
                Effect: "Allow",
                Action: [
                  "s3:GetObject",
                  "s3:PutObject",
                  "s3:DeleteObject",
                  "s3:AbortMultipartUpload",
                  "s3:ListBucket",
                ],
                Resource: [privateArn, `${privateArn}/*`],
              },
              {
                Sid: "PublicBucket",
                Effect: "Allow",
                Action: ["s3:PutObject", "s3:DeleteObject"],
                Resource: [`${publicArn}/*`],
              },
              {
                Sid: "Invalidate",
                Effect: "Allow",
                Action: ["cloudfront:CreateInvalidation"],
                Resource: [distributionArn],
              },
            ],
          }),
        ),
    },
    opts,
  );

  // --- Lambda ----------------------------------------------------------------
  const lambda = new aws.lambda.Function(
    "api",
    {
      runtime: LAMBDA_RUNTIME,
      architectures: [LAMBDA_ARCHITECTURE],
      handler: cfg.lambdaHandler,
      memorySize: cfg.lambdaMemoryMb,
      timeout: cfg.lambdaTimeoutSeconds,
      role: role.arn,
      code: inputs.code,
      environment: { variables: lambdaEnvironment(inputs) },
    },
    opts,
  );

  const lambdaLogGroup = new aws.cloudwatch.LogGroup(
    "lambda-logs",
    {
      name: pulumi.interpolate`/aws/lambda/${lambda.name}`,
      retentionInDays: cfg.logRetentionDays,
    },
    opts,
  );

  // --- API Gateway REST API (regional) --------------------------------------
  const restApi = new aws.apigateway.RestApi(
    "api",
    {
      description: "share dashboard + private content API",
      endpointConfiguration: { types: "REGIONAL" },
      // Resource policy: Cloudflare-only ingress (defense in depth).
      policy: JSON.stringify(buildResourcePolicy()),
    },
    opts,
  );

  // Catch-all proxy -> Lambda for both the root and every sub-path.
  const proxyResource = new aws.apigateway.Resource(
    "proxy",
    {
      restApi: restApi.id,
      parentId: restApi.rootResourceId,
      pathPart: "{proxy+}",
    },
    opts,
  );

  const rootMethod = new aws.apigateway.Method(
    "root-any",
    {
      restApi: restApi.id,
      resourceId: restApi.rootResourceId,
      httpMethod: "ANY",
      authorization: "NONE",
    },
    opts,
  );
  const proxyMethod = new aws.apigateway.Method(
    "proxy-any",
    {
      restApi: restApi.id,
      resourceId: proxyResource.id,
      httpMethod: "ANY",
      authorization: "NONE",
    },
    opts,
  );

  const rootIntegration = new aws.apigateway.Integration(
    "root-integration",
    {
      restApi: restApi.id,
      resourceId: restApi.rootResourceId,
      httpMethod: rootMethod.httpMethod,
      type: "AWS_PROXY",
      integrationHttpMethod: "POST",
      uri: lambda.invokeArn,
    },
    opts,
  );
  const proxyIntegration = new aws.apigateway.Integration(
    "proxy-integration",
    {
      restApi: restApi.id,
      resourceId: proxyResource.id,
      httpMethod: proxyMethod.httpMethod,
      type: "AWS_PROXY",
      integrationHttpMethod: "POST",
      uri: lambda.invokeArn,
    },
    opts,
  );

  new aws.lambda.Permission(
    "api-invoke",
    {
      action: "lambda:InvokeFunction",
      function: lambda.name,
      principal: "apigateway.amazonaws.com",
      sourceArn: pulumi.interpolate`${restApi.executionArn}/*/*`,
    },
    opts,
  );

  // Access logging requires an account-level CloudWatch role.
  const apiGatewayLogRole = new aws.iam.Role(
    "apigw-cloudwatch-role",
    {
      // Physical name MUST start with "share-" (see lambda role above).
      namePrefix: "share-apigw-logs-",
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "apigateway.amazonaws.com" },
            Action: "sts:AssumeRole",
          },
        ],
      }),
    },
    opts,
  );
  new aws.iam.RolePolicyAttachment(
    "apigw-cloudwatch-attach",
    {
      role: apiGatewayLogRole.name,
      policyArn:
        "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs",
    },
    opts,
  );
  const apiGatewayAccount = new aws.apigateway.Account(
    "apigw-account",
    { cloudwatchRoleArn: apiGatewayLogRole.arn },
    opts,
  );

  const accessLogGroup = new aws.cloudwatch.LogGroup(
    "api-access-logs",
    {
      name: pulumi.interpolate`/aws/apigateway/${restApi.name}/access`,
      retentionInDays: cfg.logRetentionDays,
    },
    opts,
  );

  const deployment = new aws.apigateway.Deployment(
    "api-deployment",
    {
      restApi: restApi.id,
      // Re-deploy when the wired routes change.
      triggers: {
        redeploy: pulumi
          .all([
            proxyResource.id,
            rootMethod.id,
            proxyMethod.id,
            rootIntegration.id,
            proxyIntegration.id,
          ])
          .apply((ids) => JSON.stringify(ids)),
      },
    },
    { ...opts, dependsOn: [rootIntegration, proxyIntegration] },
  );

  const stage = new aws.apigateway.Stage(
    "api-stage",
    {
      restApi: restApi.id,
      deployment: deployment.id,
      stageName: "v1",
      accessLogSettings: {
        destinationArn: accessLogGroup.arn,
        format: ACCESS_LOG_FORMAT,
      },
    },
    { ...opts, dependsOn: [apiGatewayAccount] },
  );

  // --- Regional custom domains for both PRIVATE hosts ------------------------
  const privateHosts: ReadonlyArray<{ key: string; host: string }> = [
    { key: "dashboard", host: cfg.dashboardHost },
    { key: "private", host: cfg.privateHost },
  ];

  const certificates: aws.acm.Certificate[] = [];
  const customDomains: aws.apigateway.DomainName[] = [];
  const basePathMappings: aws.apigateway.BasePathMapping[] = [];

  for (const { key, host } of privateHosts) {
    const certificate = new aws.acm.Certificate(
      `${key}-cert`,
      { domainName: host, validationMethod: "DNS" },
      opts,
    );
    const domain = new aws.apigateway.DomainName(
      `${key}-domain`,
      {
        domainName: host,
        regionalCertificateArn: certificate.arn,
        endpointConfiguration: { types: "REGIONAL" },
        securityPolicy: "TLS_1_2",
      },
      opts,
    );
    const mapping = new aws.apigateway.BasePathMapping(
      `${key}-mapping`,
      {
        restApi: restApi.id,
        stageName: stage.stageName,
        domainName: domain.domainName,
      },
      opts,
    );
    certificates.push(certificate);
    customDomains.push(domain);
    basePathMappings.push(mapping);
  }

  return {
    role,
    lambda,
    lambdaLogGroup,
    restApi,
    stage,
    accessLogGroup,
    apiGatewayAccount,
    certificates,
    customDomains,
    basePathMappings,
  };
}
