#!/usr/bin/env bash
#
# Post-deploy boundary checks (slice 14, story 42).
#
# The deployed ingress chain has security boundaries that no `pulumi preview` or
# unit test can prove — they only exist once Cloudflare + API Gateway + CloudFront
# are live. This script exercises each one with a real HTTP request and asserts
# the externally observable status code. Run it after `mise run deploy`:
#
#     mise run boundary-checks
#
# It is the executable form of the slice-14 runbook's "deployed-boundary checks".
# Nothing here mutates state; every request is a GET.
#
# The boundaries asserted (all PRD/AGENTS guardrails):
#
#   1. Access-gated private route returns 200 *with* a valid Access credential.
#      This boundary is NOT automatable here and is reported as a manual step:
#      the owner-only Access policy includes a single human email, and the
#      app-level verifier hard-requires that `email` claim, so the only principal
#      that can ever earn a 200 is the owner authenticated in a browser through
#      the Cloudflare Access IdP login. A Cloudflare Access service token is a
#      non-human identity (it carries `common_name`/`sub`, never `email`): the
#      email-only Access policy rejects it at the edge (403) and the verifier
#      would reject it at Lambda (401) too, so a service token can never return
#      200 against this gate. Verify the 200 in-browser after the Access login.
#   2. A raw API Gateway invoke from a non-Cloudflare IP -> 403. The API Gateway
#      resource policy DENYs every source IP outside the checked-in Cloudflare
#      ranges, so hitting the regional execute-api endpoint directly is refused.
#   3. `public.usercontent.example` must NEVER reach Lambda: it is DNS-only to
#      CloudFront, so a dashboard/API path there resolves at the CDN (403/404),
#      not a Lambda 200.
#   4. Both `/u/{sha}` and `/u/{sha}/` load unauthenticated on the public host
#      (the CloudFront rewrite function maps both shapes to the object index).
#
# Hosts and the sample SHA come from the environment (or the checked-in
# production defaults). Override per run, e.g.:
#
#     PUBLIC_SHA=<a-published-sha> mise run boundary-checks
#
set -uo pipefail

DASHBOARD_HOST="${SHARE_DASHBOARD_HOST:-share.example.com}"
PRIVATE_HOST="${SHARE_PRIVATE_HOST:-private.usercontent.example}"
PUBLIC_HOST="${SHARE_PUBLIC_HOST:-public.usercontent.example}"

# A regional API Gateway execute-api endpoint to hit directly (bypassing
# Cloudflare) for check #2. Set API_GATEWAY_INVOKE_URL to the stack's
# `restApiId.execute-api.<region>.amazonaws.com/v1` host; pull it from
# `pulumi stack output restApiId`.
API_GATEWAY_INVOKE_URL="${API_GATEWAY_INVOKE_URL:-}"

# A SHA of any published (public) item, for check #4.
PUBLIC_SHA="${PUBLIC_SHA:-}"

fail=0
pass() { printf '  ok   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fail=1; }
skip() { printf '  skip %s\n' "$1"; }

# `curl` status helper: prints the HTTP status of a GET (curl emits "000" on a
# connection/resolution failure via -w, so no extra fallback is needed).
status() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" 2>/dev/null
}

echo "share post-deploy boundary checks"
echo "  dashboard=$DASHBOARD_HOST private=$PRIVATE_HOST public=$PUBLIC_HOST"
echo

# 1. Access-gated route returns 200 with the owner's in-browser credential. ----
# Not automatable: the owner-only Access policy + email-claim-requiring verifier
# admit only the owner's browser-issued JWT. A service token (a non-human
# identity with no `email` claim) is rejected by Access at the edge and by the
# verifier at Lambda, so it can never reach 200 here — there is nothing to
# automate. Report it as a manual step rather than a spurious pass/fail.
echo "[1] Access-gated private route returns 200 (owner, in-browser)"
skip "manual: log in to https://${DASHBOARD_HOST}/ via Cloudflare Access and confirm GET /api/content -> 200 (owner-only policy + email-claim verifier make this in-browser-only; not automatable via a service token)"
echo

# 2. Raw API Gateway invoke from a non-Cloudflare IP -> 403. --------------------
echo "[2] Raw API Gateway invoke (non-Cloudflare IP) -> 403"
if [[ -n "$API_GATEWAY_INVOKE_URL" ]]; then
  code="$(status "https://${API_GATEWAY_INVOKE_URL%/}/api/content")"
  [[ "$code" == "403" ]] && pass "direct execute-api invoke -> 403 (resource policy DENY)" \
    || bad "direct execute-api invoke -> $code (expected 403)"
else
  skip "set API_GATEWAY_INVOKE_URL (pulumi stack output restApiId) to run this check"
fi
echo

# 3. public.usercontent.example must never reach Lambda. -------------------------
echo "[3] public host never reaches Lambda (DNS-only to CloudFront)"
code="$(status "https://${PUBLIC_HOST}/api/content")"
if [[ "$code" == "403" || "$code" == "404" ]]; then
  pass "GET https://${PUBLIC_HOST}/api/content -> $code (CDN, not Lambda)"
elif [[ "$code" == "200" ]]; then
  bad "GET https://${PUBLIC_HOST}/api/content -> 200 (a dashboard API leaked to the public host!)"
else
  bad "GET https://${PUBLIC_HOST}/api/content -> $code (expected 403/404 from the CDN)"
fi
echo

# 4. Both /u/{sha} and /u/{sha}/ load unauthenticated on the public host. ------
echo "[4] both /u/{sha} and /u/{sha}/ load unauthenticated"
if [[ -n "$PUBLIC_SHA" ]]; then
  for path in "/u/${PUBLIC_SHA}" "/u/${PUBLIC_SHA}/"; do
    code="$(status "https://${PUBLIC_HOST}${path}")"
    [[ "$code" == "200" ]] && pass "GET https://${PUBLIC_HOST}${path} -> 200" \
      || bad "GET https://${PUBLIC_HOST}${path} -> $code (expected 200)"
  done
else
  skip "set PUBLIC_SHA=<a-published-sha> to run the slash/no-slash check"
fi
echo

if [[ "$fail" -ne 0 ]]; then
  echo "boundary checks: FAILED"
  exit 1
fi
echo "boundary checks: all run checks passed"
