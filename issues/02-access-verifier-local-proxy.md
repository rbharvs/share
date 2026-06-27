# [02] Cloudflare Access JWT verifier + local Access-compatible proxy

**Labels:** ready-for-dev
**User stories:** 1, 38, 39
**Layers cut:** auth, api, service, tests
**Est. production LOC:** ~415

## What to build

The authentication core that gates every private route, plus the local-dev mechanism that exercises the *identical* verification path without disabling auth.

An `AccessVerifier.verify(token, host) -> Principal` deep module: per-host `AccessConfig` (issuer / audience / jwks_url), a `JwksProvider` Protocol with a module-level `CachingJwksProvider` (TTL cache + exp leeway, one fetch per cold start reused across warm invocations, injected fetch fn) and a `StaticJwksProvider` for tests. A `require_principal(host_kind)` FastAPI dependency adapts the `Cf-Access-Jwt-Assertion` header to a `Principal` or raises `auth_required`/`auth_invalid`/`host_not_allowed` mapped through the slice-01 error mapper.

A `LocalAccessSigner` mints fresh Cloudflare-shaped RS256 JWTs per request and serves a JWKS endpoint, proving the verifier accepts locally-minted tokens through the same code path. (The browser reverse-proxy *forwarding* that injects the header is deferred to slice 09 where Vite exists; this slice ships the token mint/JWKS core only.)

Resolved decisions (from spike — RS256 verify ran green for happy path + every rejection case):

- **Lib = `PyJWT[crypto]`** (RS256 only). One decode does signature + iss + aud + exp + required-claims:
  ```python
  jwt.decode(token, key, algorithms=["RS256"], audience=cfg.audience,
             issuer=cfg.issuer, options={"require": ["exp", "iss", "aud"]})
  ```
  then check `claims["email"].lower() == cfg.allowed_email` (plain lowercased `str` compare — `pydantic.EmailStr` dropped to avoid the `email-validator` dependency). Fail closed on any miss.
- **`cryptography` is a native dep** (pulled in by `PyJWT[crypto]`), colliding with the PRD's pure-Python/no-Docker vendored-zip assumption. Resolution: vendor the arm64 manylinux wheel via `uv --python-platform` (settled in slice 11); no Docker pivot, no Lambda layers.
- **No local auth bypass** — only the injected `AccessConfig` differs between prod and local; a local-issuer token is rejected on a prod-configured host. The host string is the shared join key with the slice-01 gate and the URL builder.

## Acceptance criteria

- [ ] `verify()` is byte-identical for Cloudflare-minted and locally-minted tokens; only injected `AccessConfig` differs.
- [ ] `ALLOWED_ALGS=["RS256"]`, `jwt.decode` requires `exp`/`iss`/`aud`; `alg=none` and RS/HS confusion rejected before key lookup.
- [ ] All PRD auth cases covered by tests via `StaticJwksProvider`: valid accepted; missing / bad-sig / wrong-iss / wrong-aud / expired / wrong-email / missing-claim / unknown-kid / `alg=none` rejected; dashboard-audience-on-private-host and private-audience-on-dashboard-host both rejected; local-issuer rejected on a prod host.
- [ ] `AuthError.code`/`.status_code` map 1:1 onto `auth_required`/`auth_invalid`/`host_not_allowed` through the slice-01 error mapper.
- [ ] JWKS fetched once then served from cache; key-rotation force-refresh recovers; module-level provider reuses cache across warm invocations.
- [ ] A real-HTTP roundtrip test: `LocalAccessSigner` mints a token + serves JWKS → verifier accepts it through the identical path.

## Blocked by

- #01 — Walking skeleton (error mapper, host registry, settings DI)
