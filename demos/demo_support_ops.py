#!/usr/bin/env python3
"""Demo: Retail Support-Ops verification pipeline.

Scenario: An AI agent handles a customer cancellation request.
The agent must (1) cancel the order, (2) process a refund, and
(3) update inventory.  We compose three HARD verifiers with
fail-closed policy - if ANY state check fails, the whole episode
fails, regardless of what the agent *says* it did.

Usage:
    pip install vrdev
    python demo_support_ops.py
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Embedded mock retail API ────────────────────────────────────────────────

ORDERS = {
    "ORD-001": {"order_id": "ORD-001", "status": "cancelled", "reason": "customer_request", "customer_id": "C-100"},
    "ORD-002": {"order_id": "ORD-002", "status": "active", "reason": None, "customer_id": "C-200"},
}

REFUNDS = {
    "RF-001": {"refund_id": "RF-001", "order_id": "ORD-001", "status": "processed", "amount": 49.99, "reason": "customer_request"},
    "RF-002": {"refund_id": "RF-002", "order_id": "ORD-002", "status": "pending", "amount": 129.00, "reason": "defective_item"},
}

INVENTORY = {
    "SKU-100": {"sku": "SKU-100", "name": "Widget A", "quantity": 42, "warehouse": "WH-EAST"},
    "SKU-200": {"sku": "SKU-200", "name": "Widget B", "quantity": 0, "warehouse": "WH-WEST"},
}


class _RetailHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        if path.startswith("/orders/"):
            self._lookup(ORDERS, path.split("/")[-1], "Order")
        elif path.startswith("/refunds/"):
            self._lookup(REFUNDS, path.split("/")[-1], "Refund")
        elif path.startswith("/inventory/"):
            self._lookup(INVENTORY, path.split("/")[-1], "SKU")
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
        pass  # suppress request logs


def _start_mock_server() -> str:
    server = HTTPServer(("127.0.0.1", 0), _RetailHandler)
    host, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://{host}:{port}"


# ── Demo ────────────────────────────────────────────────────────────────────

def main() -> None:
    from vrdev.core.compose import compose
    from vrdev.core.registry import get_verifier
    from vrdev.core.types import PolicyMode, VerifierInput

    api_base = _start_mock_server()
    print(f"Mock retail API running at {api_base}\n")

    # Get verifiers from registry
    order_v = get_verifier("vr/tau2.retail.order_cancelled")
    refund_v = get_verifier("vr/tau2.retail.refund_processed")
    inventory_v = get_verifier("vr/tau2.retail.inventory_updated")

    # Compose with fail-closed hard gating
    composed = compose(
        [order_v, refund_v, inventory_v],
        require_hard=True,
        policy_mode=PolicyMode.FAIL_CLOSED,
    )

    # ── Scenario 1: Everything correct ──────────────────────────────────
    print("=" * 60)
    print("SCENARIO 1: Agent correctly cancelled order + processed refund")
    print("=" * 60)

    input_pass = VerifierInput(
        completions=["I have cancelled order ORD-001, processed refund RF-001 ($49.99), and updated inventory for SKU-100."],
        ground_truth={
            "order_id": "ORD-001",
            # order verifier defaults expected_status to "cancelled" ✓
            "expected_reason": "customer_request",
            "refund_id": "RF-001",
            # refund verifier defaults expected_status to "processed" ✓
            "expected_amount": 49.99,
            "sku": "SKU-100",
            "expected_quantity": 42,
            "expected_warehouse": "WH-EAST",
        },
        context={"api_base_url": api_base},
    )

    results = composed.verify(input_pass)
    r = results[0]
    print(f"  Verdict:  {r.verdict.value}")
    print(f"  Score:    {r.score:.2f}")
    print(f"  Breakdown: {json.dumps(r.breakdown, indent=4)}")
    print(f"  Evidence hash: {r.artifact_hash[:16]}...")
    print()

    # ── Scenario 2: Agent claims success but state is wrong ─────────────
    print("=" * 60)
    print("SCENARIO 2: Agent CLAIMS success - but order is still active!")
    print("=" * 60)

    input_fail = VerifierInput(
        completions=["Done! I cancelled order ORD-002 and refunded RF-002. Inventory updated for SKU-200."],
        ground_truth={
            "order_id": "ORD-002",
            # order verifier defaults expected_status to "cancelled" - but actual is "active"!
            "refund_id": "RF-002",
            # refund verifier defaults expected_status to "processed" - but actual is "pending"!
            "expected_amount": 129.00,
            "sku": "SKU-200",
            "expected_quantity": 10,  # actual is 0!
            "expected_warehouse": "WH-WEST",
        },
        context={"api_base_url": api_base},
    )

    results = composed.verify(input_fail)
    r = results[0]
    print(f"  Verdict:  {r.verdict.value}")
    print(f"  Score:    {r.score:.2f}")
    print(f"  Breakdown: {json.dumps(r.breakdown, indent=4)}")
    if r.metadata.hard_gate_failed:
        print("  ⚠ Hard gate triggered - fail-closed policy caught the lie")
    print()

    # ── Summary ─────────────────────────────────────────────────────────
    print("KEY TAKEAWAY:")
    print("  The agent in Scenario 2 said 'Done!' - an LLM-as-judge might")
    print("  score that highly.  But the HARD verifiers checked actual API")
    print("  state and caught 3 mismatches: order still active, refund")
    print("  pending, inventory wrong.  That's verifiable rewards.")


if __name__ == "__main__":
    main()
