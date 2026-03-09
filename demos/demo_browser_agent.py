#!/usr/bin/env python3
"""Demo: Browser/e-commerce agent verification pipeline.

Scenario: An AI agent places orders on an e-commerce site.
We verify the order was actually placed AND cross-check the
refund system - composing verifiers from two different domains
(WebArena e-commerce + τ²-bench retail) to catch edge cases.

This demo uses HTTP-level verifiers only (no Playwright needed).
For visual/DOM verification, vrdev also ships element_visible
and screenshot_match verifiers that require a browser.

Usage:
    pip install vrdev
    python demo_browser_agent.py
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Embedded mock e-commerce + refund APIs ──────────────────────────────────

ORDERS = {
    "WEB-001": {
        "order_id": "WEB-001",
        "status": "confirmed",
        "items": ["Widget A", "Widget B"],
        "total": 49.98,
        "customer_id": "C-100",
    },
    "WEB-003": {
        "order_id": "WEB-003",
        "status": "cancelled",
        "items": ["Widget A"],
        "total": 24.99,
        "customer_id": "C-300",
    },
}

REFUNDS = {
    "RF-101": {
        "refund_id": "RF-101",
        "order_id": "WEB-001",
        "status": "processed",
        "amount": 49.98,
        "reason": "return",
    },
    "RF-103": {
        "refund_id": "RF-103",
        "order_id": "WEB-003",
        "status": "denied",
        "amount": 0.0,
        "reason": "policy_violation",
    },
}


class _EcommerceHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        if path.startswith("/orders/"):
            self._lookup(ORDERS, path.split("/")[-1], "Order")
        elif path.startswith("/refunds/"):
            self._lookup(REFUNDS, path.split("/")[-1], "Refund")
        else:
            self._json(404, {"error": "Not found"})

    def _lookup(self, store: dict, key: str, label: str) -> None:
        if key in store:
            self._json(200, store[key])
        else:
            self._json(404, {"error": f"{label} {key} not found"})

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _start_mock_server() -> str:
    server = HTTPServer(("127.0.0.1", 0), _EcommerceHandler)
    host, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://{host}:{port}"


# ── Demo ────────────────────────────────────────────────────────────────────

def main() -> None:
    from vrdev.core.compose import compose
    from vrdev.core.registry import get_verifier
    from vrdev.core.types import PolicyMode, VerifierInput

    api_base = _start_mock_server()
    print(f"Mock e-commerce API running at {api_base}\n")

    # Cross-domain composition: WebArena order + τ²-bench refund
    order_v = get_verifier("vr/web.ecommerce.order_placed")
    refund_v = get_verifier("vr/tau2.retail.refund_processed")

    composed = compose(
        [order_v, refund_v],
        require_hard=True,
        policy_mode=PolicyMode.FAIL_CLOSED,
    )

    # ── Scenario 1: Valid order + processed refund ──────────────────────
    print("=" * 60)
    print("SCENARIO 1: Agent placed order WEB-001, refund RF-101 processed")
    print("=" * 60)

    input_pass = VerifierInput(
        completions=[
            "I placed order WEB-001 for Widget A and Widget B (total $49.98). "
            "Refund RF-101 has been processed for the full amount."
        ],
        ground_truth={
            # For OrderPlacedVerifier
            "order_id": "WEB-001",
            "expected_items": ["Widget A", "Widget B"],
            "expected_total": 49.98,
            # For RefundProcessedVerifier
            "refund_id": "RF-101",
            "expected_amount": 49.98,
        },
        context={"api_base_url": api_base},
    )

    results = composed.verify(input_pass)
    r = results[0]
    print(f"  Verdict:  {r.verdict.value}")
    print(f"  Score:    {r.score:.2f}")
    print(f"  Breakdown: {json.dumps(r.breakdown, indent=4)}")
    print()

    # ── Scenario 2: Cancelled order + denied refund ─────────────────────
    print("=" * 60)
    print("SCENARIO 2: Agent claims success - but order was cancelled!")
    print("=" * 60)

    input_fail = VerifierInput(
        completions=[
            "Order WEB-003 placed successfully! Refund RF-103 processed."
        ],
        ground_truth={
            "order_id": "WEB-003",
            "expected_items": ["Widget A"],
            "expected_total": 24.99,
            "refund_id": "RF-103",
            "expected_amount": 24.99,  # actual is 0.0 (denied)
        },
        context={"api_base_url": api_base},
    )

    results = composed.verify(input_fail)
    r = results[0]
    print(f"  Verdict:  {r.verdict.value}")
    print(f"  Score:    {r.score:.2f}")
    print(f"  Breakdown: {json.dumps(r.breakdown, indent=4)}")
    if r.metadata.hard_gate_failed:
        print("  ⚠ Hard gate triggered - order was cancelled + refund denied")
    print()

    # ── Summary ─────────────────────────────────────────────────────────
    print("KEY TAKEAWAY:")
    print("  Cross-domain composition lets you verify BOTH the e-commerce")
    print("  platform state AND the payment/refund state in a single call.")
    print("  The agent in Scenario 2 said 'placed successfully' - but the")
    print("  order was actually cancelled and the refund was denied.")
    print()
    print("NOTE: This demo uses HTTP-level verifiers.  vrdev also ships")
    print("  web.browser.element_visible and web.browser.screenshot_match")
    print("  for visual DOM verification (requires Playwright).")


if __name__ == "__main__":
    main()
