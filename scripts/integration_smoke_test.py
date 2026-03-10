#!/usr/bin/env python3
"""Live integration smoke test for vr.dev hosted API.

Tests HARD, SOFT, and composed pipelines against the production (or staging) API.
Requires a valid API key. Designed for CI or manual pre-launch validation.

Usage:
    # Set required env vars
    export VR_API_URL=https://api.vr.dev   # or http://localhost:8000
    export VR_API_KEY=your-api-key

    # Run all tests
    python scripts/integration_smoke_test.py

    # Run only HARD tier (no OpenAI dependency)
    python scripts/integration_smoke_test.py --tier hard

    # Run with verbose output
    python scripts/integration_smoke_test.py -v

Exit codes:
    0 = all tests passed
    1 = one or more tests failed
    2 = configuration error (missing env vars)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# ── Config ───────────────────────────────────────────────────────────────────

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m⊘\033[0m"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ── HTTP helper ──────────────────────────────────────────────────────────────


def api_request(
    base_url: str,
    path: str,
    api_key: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 30,
) -> tuple[int, dict]:
    """Make an API request and return (status_code, parsed_json)."""
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read())
        except Exception:
            err_body = {"detail": str(e)}
        return e.code, err_body


# ── Test runner ──────────────────────────────────────────────────────────────


class TestRunner:
    def __init__(self, base_url: str, api_key: str, verbose: bool = False):
        self.base_url = base_url
        self.api_key = api_key
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results: list[dict] = []

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        if ok:
            print(f"  {PASS} {label}")
            self.passed += 1
        else:
            msg = f"{label}: {detail}" if detail else label
            print(f"  {FAIL} {msg}")
            self.failed += 1
        self.results.append({"label": label, "ok": ok, "detail": detail})
        return ok

    def skip(self, label: str, reason: str = ""):
        msg = f"{label}: {reason}" if reason else label
        print(f"  {SKIP} {msg}")
        self.skipped += 1
        self.results.append({"label": label, "ok": None, "detail": reason})

    def log(self, msg: str):
        if self.verbose:
            print(f"    → {msg}")

    def verify(
        self, verifier_id: str, completions: list[str], ground_truth: dict, timeout: int = 30
    ) -> tuple[int, dict]:
        return api_request(
            self.base_url,
            "/v1/verify",
            self.api_key,
            method="POST",
            body={
                "verifier_id": verifier_id,
                "completions": completions,
                "ground_truth": ground_truth,
            },
            timeout=timeout,
        )

    def compose(
        self,
        verifier_ids: list[str],
        completions: list[str],
        ground_truth: dict,
        policy_mode: str = "fail_closed",
        timeout: int = 30,
    ) -> tuple[int, dict]:
        return api_request(
            self.base_url,
            "/v1/compose",
            self.api_key,
            method="POST",
            body={
                "verifier_ids": verifier_ids,
                "completions": completions,
                "ground_truth": ground_truth,
                "policy_mode": policy_mode,
            },
            timeout=timeout,
        )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_health(t: TestRunner):
    """Test /health endpoint."""
    print("\n[1/6] Health check")
    status, body = api_request(t.base_url, "/health", t.api_key, timeout=10)
    t.check("GET /health returns 200", status == 200, f"got {status}")
    t.check("status is ok", body.get("status") == "ok", f"got {body}")
    t.log(f"version: {body.get('version', '?')}")


def test_list_verifiers(t: TestRunner):
    """Test GET /v1/verifiers returns the full registry."""
    print("\n[2/6] List verifiers")
    status, body = api_request(t.base_url, "/v1/verifiers", t.api_key, timeout=10)
    t.check("GET /v1/verifiers returns 200", status == 200, f"got {status}")
    verifiers = body.get("verifiers", [])
    t.check("registry has ≥38 verifiers", len(verifiers) >= 38, f"got {len(verifiers)}")
    t.log(f"verifiers: {len(verifiers)}")


def test_hard_tier(t: TestRunner):
    """Test HARD-tier verifiers using pre_result mode (no external resources needed)."""
    print("\n[3/6] HARD tier — api.http.status_ok (pre_result mode)")

    # Positive case: status 200 matches expected
    status, body = t.verify(
        "vr/api.http.status_ok",
        ["Health check returned 200"],
        {"expected_status": 200, "pre_result": {"status_code": 200}},
    )
    t.check("HARD positive: 200 response", status == 200, f"got {status}: {body}")
    if status == 200:
        r = body["results"][0]
        t.check("HARD positive: verdict PASS", r["verdict"] == "PASS", f"got {r['verdict']}")
        t.check("HARD positive: score 1.0", r["score"] == 1.0, f"got {r['score']}")
        t.check("HARD positive: tier is HARD", r["tier"] == "HARD", f"got {r['tier']}")
        t.check("HARD positive: has artifact_hash", bool(r.get("artifact_hash")), "missing")
        t.check("HARD positive: has evidence dict", isinstance(r.get("evidence"), dict), "missing")
        t.log(f"artifact_hash: {r.get('artifact_hash', '?')[:16]}...")
        t.log(f"evidence keys: {list(r.get('evidence', {}).keys())}")

    # Negative case: status mismatch
    status2, body2 = t.verify(
        "vr/api.http.status_ok",
        ["Server returned 500"],
        {"expected_status": 200, "pre_result": {"status_code": 500}},
    )
    t.check("HARD negative: 200 response", status2 == 200, f"got {status2}: {body2}")
    if status2 == 200:
        r2 = body2["results"][0]
        t.check("HARD negative: verdict FAIL", r2["verdict"] == "FAIL", f"got {r2['verdict']}")
        t.check("HARD negative: score 0.0", r2["score"] == 0.0, f"got {r2['score']}")


def test_soft_tier(t: TestRunner):
    """Test a SOFT-tier verifier (requires OpenAI API key on the server)."""
    print("\n[4/6] SOFT tier — rubric.email.tone_professional")

    # Professional email — should score well
    email = (
        "Dear Customer,\n\n"
        "Thank you for contacting our support team. Your order ORD-42 has been "
        "successfully cancelled as requested. You will receive a full refund "
        "within 5-7 business days to your original payment method.\n\n"
        "If you have any further questions, please don't hesitate to reach out.\n\n"
        "Best regards,\nSupport Team"
    )
    t0 = time.monotonic()
    status, body = t.verify(
        "vr/rubric.email.tone_professional",
        [email],
        {"key_information_required": ["order ID", "refund timeline"]},
        timeout=60,  # SOFT tier calls OpenAI, may be slower
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    t.log(f"latency: {elapsed_ms}ms")

    t.check("SOFT positive: 200 response", status == 200, f"got {status}: {body}")
    if status == 200:
        r = body["results"][0]
        t.check("SOFT positive: tier is SOFT", r["tier"] == "SOFT", f"got {r['tier']}")
        t.check("SOFT positive: score > 0.5", r["score"] > 0.5, f"got {r['score']}")
        t.check(
            "SOFT positive: verdict PASS",
            r["verdict"] == "PASS",
            f"got {r['verdict']} (score={r['score']})",
        )
        t.check("SOFT positive: has artifact_hash", bool(r.get("artifact_hash")), "missing")

        ev = r.get("evidence", {})
        t.check(
            "SOFT positive: evidence has judge_model",
            bool(ev.get("judge_model")),
            f"evidence keys: {list(ev.keys())}",
        )
        t.check(
            "SOFT positive: evidence has judge_response",
            bool(ev.get("judge_response")),
            "missing — OpenAI may not be configured",
        )
        t.log(f"judge_model: {ev.get('judge_model', '?')}")
        t.log(f"score: {r['score']}")
        t.log(f"breakdown: {r.get('breakdown', {})}")
    elif status == 500:
        t.check(
            "SOFT positive: server error (likely missing OPENAI_API_KEY)",
            False,
            f"500 — check that VRDEV_OPENAI_API_KEY or OPENAI_API_KEY is set on the server",
        )

    # Unprofessional email — should score poorly
    bad_email = "yo dude ur order is cancelled lol deal with it"
    status2, body2 = t.verify(
        "vr/rubric.email.tone_professional",
        [bad_email],
        {"key_information_required": ["order ID", "refund timeline"]},
        timeout=60,
    )
    if status2 == 200:
        r2 = body2["results"][0]
        t.check("SOFT negative: score < 0.75", r2["score"] < 0.75, f"got {r2['score']}")
        t.log(f"bad email score: {r2['score']}, breakdown: {r2.get('breakdown', {})}")


def test_compose(t: TestRunner):
    """Test composed pipeline with hard-gating."""
    print("\n[5/6] Composition — HARD + SOFT with hard-gating")

    # HARD (pre_result) passes, then SOFT rubric runs
    status, body = t.compose(
        ["vr/api.http.status_ok", "vr/rubric.email.tone_professional"],
        ["Dear Customer,\n\nYour order #12345 has been cancelled. A full refund will be issued within 5-7 business days.\n\nBest regards,\nSupport Team"],
        {
            "expected_status": 200,
            "pre_result": {"status_code": 200},
            "key_information_required": ["order number", "refund timeline"],
        },
        timeout=60,
    )
    t.check("compose: 200 response", status == 200, f"got {status}: {body}")
    if status == 200:
        results = body.get("results", [])
        t.check("compose: has results", len(results) > 0, "empty results")
        if results:
            t.log(f"composed results: {len(results)}")
            for i, r in enumerate(results):
                t.log(f"  result[{i}]: verdict={r['verdict']}, score={r['score']}, tier={r['tier']}")


def test_evidence_retrieval(t: TestRunner):
    """Test evidence storage and retrieval — verifies the audit trail works."""
    print("\n[6/6] Evidence storage & retrieval")

    # First, do a verification to generate evidence
    status, body = t.verify(
        "vr/api.http.status_ok",
        ["Health check returned 200"],
        {"expected_status": 200, "pre_result": {"status_code": 200}},
    )
    if status != 200:
        t.skip("evidence retrieval", "verification failed, can't test evidence")
        return

    artifact_hash = body["results"][0].get("artifact_hash")
    if not artifact_hash:
        t.skip("evidence retrieval", "no artifact_hash returned")
        return

    t.log(f"artifact_hash: {artifact_hash}")

    # Retrieve it
    status2, body2 = api_request(
        t.base_url, f"/v1/evidence/{artifact_hash}", t.api_key, timeout=10
    )
    t.check("evidence GET: 200 response", status2 == 200, f"got {status2}: {body2}")
    if status2 == 200:
        t.check(
            "evidence: hash matches",
            body2.get("artifact_hash") == artifact_hash,
            f"got {body2.get('artifact_hash')}",
        )
        t.check("evidence: has verdict", bool(body2.get("verdict")), "missing")
        t.check("evidence: has created_at", bool(body2.get("created_at")), "missing")
        t.log(f"evidence stored at: {body2.get('created_at', '?')}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="vr.dev live API integration smoke test")
    parser.add_argument(
        "--tier",
        choices=["all", "hard", "soft"],
        default="all",
        help="Which tiers to test (default: all)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed output")
    parser.add_argument("--url", default="", help="Override VR_API_URL")
    parser.add_argument("--key", default="", help="Override VR_API_KEY")
    parser.add_argument("--json", action="store_true", help="Output results as JSON (for CI)")
    args = parser.parse_args()

    base_url = args.url or _env("VR_API_URL", "https://api.vr.dev")
    api_key = args.key or _env("VR_API_KEY")

    if not api_key:
        print("ERROR: VR_API_KEY environment variable is required (or use --key)")
        print("  Get one at https://vr.dev/keys")
        sys.exit(2)

    print(f"\n{'=' * 60}")
    print(f"  vr.dev Integration Smoke Test")
    print(f"  Target: {base_url}")
    print(f"  Tier:   {args.tier}")
    print(f"{'=' * 60}")

    t = TestRunner(base_url, api_key, verbose=args.verbose)

    t0 = time.monotonic()

    test_health(t)
    test_list_verifiers(t)
    test_hard_tier(t)

    if args.tier in ("all", "soft"):
        test_soft_tier(t)
        test_compose(t)
    else:
        print("\n[4/6] SOFT tier — skipped (--tier hard)")
        print("\n[5/6] Composition — skipped (--tier hard)")

    test_evidence_retrieval(t)

    total_time = time.monotonic() - t0

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Results: {t.passed} passed, {t.failed} failed, {t.skipped} skipped")
    print(f"  Time:    {total_time:.1f}s")
    print(f"{'=' * 60}\n")

    if args.json:
        output = {
            "passed": t.passed,
            "failed": t.failed,
            "skipped": t.skipped,
            "total_time_s": round(total_time, 2),
            "base_url": base_url,
            "results": t.results,
        }
        print(json.dumps(output, indent=2))

    sys.exit(0 if t.failed == 0 else 1)


if __name__ == "__main__":
    main()
