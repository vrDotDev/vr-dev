#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# readiness_smoke_test.sh — vr.dev platform readiness check
#
# Usage:
#   ./scripts/readiness_smoke_test.sh                    # uses defaults
#   VR_API_KEY=vr_live_xxx ./scripts/readiness_smoke_test.sh
#   VR_API_URL=https://api.vr.dev VR_SITE_URL=https://vr.dev ./scripts/readiness_smoke_test.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

API="${VR_API_URL:-https://api.vr.dev}"
SITE="${VR_SITE_URL:-https://vr.dev}"
KEY="${VR_API_KEY:-}"

PASS=0
FAIL=0
WARN=0

pass()  { PASS=$((PASS+1)); printf "  ✅  %s\n" "$1"; }
fail()  { FAIL=$((FAIL+1)); printf "  ❌  %s\n" "$1"; }
warn()  { WARN=$((WARN+1)); printf "  ⚠️   %s\n" "$1"; }
header(){ printf "\n━━ %s ━━\n" "$1"; }

# Curl with timeout
C="curl -s --connect-timeout 10 --max-time 15"

# ── 1. API Health ──────────────────────────────────────────────
header "API Health ($API)"

STATUS=$($C -o /dev/null -w "%{http_code}" "$API/health" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  BODY=$($C "$API/health" 2>/dev/null)
  pass "GET /health → 200  ($BODY)"
else
  fail "GET /health → $STATUS (expected 200)"
fi

# ── 2. API Endpoints (no auth) ────────────────────────────────
header "API Public Endpoints"

STATUS=$($C -o /dev/null -w "%{http_code}" "$API/v1/pricing" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  pass "GET /v1/pricing → 200"
else
  fail "GET /v1/pricing → $STATUS (expected 200)"
fi

STATUS=$($C -o /dev/null -w "%{http_code}" "$API/v1/keys" 2>/dev/null || echo "000")
if [[ "$STATUS" == "200" ]]; then
  pass "GET /v1/keys → 200 (signing public key)"
else
  fail "GET /v1/keys → $STATUS (expected 200)"
fi

# Verifiers without auth should return 402 (x402 payment required)
STATUS=$($C -o /dev/null -w "%{http_code}" "$API/v1/verifiers" 2>/dev/null || echo "000")
if [[ "$STATUS" == "402" ]]; then
  pass "GET /v1/verifiers (no auth) → 402 (x402 expected)"
elif [[ "$STATUS" == "200" ]]; then
  warn "GET /v1/verifiers (no auth) → 200 (x402 may be disabled)"
else
  fail "GET /v1/verifiers (no auth) → $STATUS (expected 402)"
fi

# ── 3. API Endpoints (authenticated) ──────────────────────────
header "API Authenticated Endpoints"

if [[ -z "$KEY" ]]; then
  warn "VR_API_KEY not set — skipping authenticated endpoint tests"
  warn "Set VR_API_KEY=vr_live_xxx to test authenticated endpoints"
else
  STATUS=$($C -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" "$API/v1/verifiers" 2>/dev/null || echo "000")
  if [[ "$STATUS" == "200" ]]; then
    COUNT=$($C -H "Authorization: Bearer $KEY" "$API/v1/verifiers" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('verifiers',d)) if isinstance(d,dict) else len(d))" 2>/dev/null || echo "?")
    pass "GET /v1/verifiers (auth) → 200  ($COUNT verifiers)"
  else
    fail "GET /v1/verifiers (auth) → $STATUS (expected 200)"
  fi

  # Run a simple verification
  VERIFY_BODY='{"verifier_id":"document.json.valid","input":{"content":"{\"test\":true}"}}'
  STATUS=$($C -o /tmp/vr_verify_result.json -w "%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    -d "$VERIFY_BODY" \
    "$API/v1/verify" 2>/dev/null || echo "000")
  if [[ "$STATUS" == "200" ]]; then
    VERDICT=$(python3 -c "import json; print(json.load(open('/tmp/vr_verify_result.json')).get('verdict','?'))" 2>/dev/null || echo "?")
    pass "POST /v1/verify (document.json.valid) → 200, verdict=$VERDICT"
  elif [[ "$STATUS" == "402" ]]; then
    warn "POST /v1/verify → 402 (payment required — x402 active)"
  else
    fail "POST /v1/verify → $STATUS (expected 200)"
  fi

  STATUS=$($C -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" "$API/v1/usage" 2>/dev/null || echo "000")
  if [[ "$STATUS" == "200" ]]; then
    pass "GET /v1/usage (auth) → 200"
  else
    fail "GET /v1/usage (auth) → $STATUS (expected 200)"
  fi

  STATUS=$($C -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $KEY" "$API/v1/evidence" 2>/dev/null || echo "000")
  if [[ "$STATUS" == "200" ]]; then
    pass "GET /v1/evidence (auth) → 200"
  elif [[ "$STATUS" == "404" ]]; then
    warn "GET /v1/evidence → 404 (endpoint may not be implemented yet)"
  else
    fail "GET /v1/evidence (auth) → $STATUS (expected 200)"
  fi
fi

# ── 4. Frontend Pages ─────────────────────────────────────────
header "Frontend Pages ($SITE)"

for PAGE in "/" "/registry" "/pricing" "/paper" "/about" "/docs" "/demos" "/terms" "/admin"; do
  STATUS=$($C -L -o /dev/null -w "%{http_code}" "$SITE$PAGE" 2>/dev/null || echo "000")
  if [[ "$STATUS" == "200" ]]; then
    pass "GET $PAGE → 200"
  elif [[ "$STATUS" == "307" || "$STATUS" == "308" || "$STATUS" == "302" ]]; then
    warn "GET $PAGE → $STATUS (redirect — may require auth)"
  else
    fail "GET $PAGE → $STATUS (expected 200)"
  fi
done

# ── 5. SDK Install Check ──────────────────────────────────────
header "SDK Availability"

PIP_STATUS=$(pip3 install --dry-run vrdev 2>&1 | head -5 || true)
if echo "$PIP_STATUS" | grep -qi "would install\|already satisfied\|requirement"; then
  INSTALLED_VER=$(pip3 show vrdev 2>/dev/null | grep "^Version:" | awk '{print $2}' || echo "not installed")
  pass "vrdev available on PyPI (installed: $INSTALLED_VER)"
else
  fail "vrdev not installable from PyPI"
fi

# ── Summary ────────────────────────────────────────────────────
header "Summary"
printf "  Passed: %d  |  Failed: %d  |  Warnings: %d\n\n" "$PASS" "$FAIL" "$WARN"

if [[ "$FAIL" -gt 0 ]]; then
  printf "🔴 %d check(s) FAILED — review above before launch\n" "$FAIL"
  exit 1
elif [[ "$WARN" -gt 0 ]]; then
  printf "🟡 All checks passed with %d warning(s)\n" "$WARN"
  exit 0
else
  printf "🟢 All checks passed — ready for launch!\n"
  exit 0
fi
