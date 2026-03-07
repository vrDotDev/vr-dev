#!/usr/bin/env python3
"""Benchmark: Soft-only vs hard-gated verification.

Runs 100 verification episodes against a mock retail API.
Each episode simulates an AI agent that either correctly or
incorrectly handles a support task.  We compare:

  1. SOFT-only: Just an LLM rubric judge (simulated via StubJudge)
  2. HARD-gated: HARD state verifier + SOFT rubric, composed with require_hard

The key finding: soft-only rewards produce false positives when the
agent says the right thing but doesn't change the right state.
Hard gating eliminates them.

Usage:
    pip install vrdev
    python benchmark_gating.py

Outputs:
    benchmark_results.json   — machine-readable results
    Summary table to stdout
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Embedded mock API with dynamic data ─────────────────────────────────────

# We generate episodes dynamically: some orders are actually cancelled,
# some are still active.  The agent always *claims* cancellation succeeded.

_dynamic_orders: dict[str, dict] = {}
_dynamic_refunds: dict[str, dict] = {}


class _BenchHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        if path.startswith("/orders/"):
            oid = path.split("/")[-1]
            if oid in _dynamic_orders:
                self._json(200, _dynamic_orders[oid])
            else:
                self._json(404, {"error": f"Order {oid} not found"})
        elif path.startswith("/refunds/"):
            rid = path.split("/")[-1]
            if rid in _dynamic_refunds:
                self._json(200, _dynamic_refunds[rid])
            else:
                self._json(404, {"error": f"Refund {rid} not found"})
        else:
            self._json(404, {"error": "Not found"})

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
    server = HTTPServer(("127.0.0.1", 0), _BenchHandler)
    host, port = server.server_address
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://{host}:{port}"


# ── Episode generator ───────────────────────────────────────────────────────

def _generate_episode(idx: int, corrupt: bool) -> dict:
    """Generate one episode's mock data and expected ground truth.

    If corrupt=True, the order stays active and refund stays pending
    (the agent is lying about success).
    """
    oid = f"ORD-{idx:04d}"
    rid = f"RF-{idx:04d}"

    if corrupt:
        _dynamic_orders[oid] = {
            "order_id": oid,
            "status": "active",
            "reason": None,
            "customer_id": f"C-{idx}",
        }
        _dynamic_refunds[rid] = {
            "refund_id": rid,
            "order_id": oid,
            "status": "pending",
            "amount": 0.0,
            "reason": "none",
        }
    else:
        _dynamic_orders[oid] = {
            "order_id": oid,
            "status": "cancelled",
            "reason": "customer_request",
            "customer_id": f"C-{idx}",
        }
        _dynamic_refunds[rid] = {
            "refund_id": rid,
            "order_id": oid,
            "status": "processed",
            "amount": 49.99,
            "reason": "customer_request",
        }

    return {
        "order_id": oid,
        "refund_id": rid,
        "corrupt": corrupt,
        "ground_truth": {
            "order_id": oid,
            # order verifier defaults expected_status to "cancelled"
            # refund verifier defaults expected_status to "processed"
            "expected_reason": "customer_request",
            "refund_id": rid,
            "expected_amount": 49.99,
            "key_information_required": ["order cancellation", "refund confirmation"],
        },
    }


# ── Benchmark ───────────────────────────────────────────────────────────────

def main() -> None:
    from vrdev.core.compose import compose
    from vrdev.core.llm import StubJudge
    from vrdev.core.registry import get_verifier
    from vrdev.core.types import PolicyMode, Verdict, VerifierInput

    random.seed(42)
    num_episodes = 100
    corrupt_ratio = 0.35  # 35% of episodes have corrupt agent outputs

    api_base = _start_mock_server()
    print(f"Mock API at {api_base}")
    print(f"Running {num_episodes} episodes ({int(corrupt_ratio * 100)}% corrupt)...\n")

    # ── Build verifiers ─────────────────────────────────────────────────

    # HARD verifiers (check actual state)
    order_v = get_verifier("vr/tau2.retail.order_cancelled")
    refund_v = get_verifier("vr/tau2.retail.refund_processed")

    # SOFT verifier (LLM rubric — always gives high score because the
    # agent's *text* sounds correct even when the state is wrong)
    soft_judge_pass = StubJudge(
        '{"greeting_present": 1, "appropriate_formality": 1, '
        '"key_info_included": 1, "no_inappropriate_content": 1}'
    )
    rubric_v = get_verifier("vr/rubric.email.tone_professional", judge=soft_judge_pass)

    # Strategy 1: Soft-only (just the rubric judge)
    soft_only = compose([rubric_v])

    # Strategy 2: Hard-gated (HARD + SOFT, require_hard=True)
    hard_gated = compose(
        [order_v, refund_v, rubric_v],
        require_hard=True,
        policy_mode=PolicyMode.FAIL_CLOSED,
    )

    # ── Run episodes ────────────────────────────────────────────────────

    results_soft: list[dict] = []
    results_hard: list[dict] = []

    for i in range(num_episodes):
        corrupt = random.random() < corrupt_ratio
        episode = _generate_episode(i, corrupt)

        # Agent always claims success
        completion = (
            f"Dear customer, your order {episode['order_id']} has been cancelled "
            f"per your request. Refund {episode['refund_id']} of $49.99 has been "
            f"processed. Confirmation number CN-{i:04d}."
        )

        inp = VerifierInput(
            completions=[completion],
            ground_truth=episode["ground_truth"],
            context={"api_base_url": api_base},
        )

        # Soft-only
        t0 = time.monotonic()
        soft_res = soft_only.verify(inp)
        soft_ms = (time.monotonic() - t0) * 1000

        results_soft.append({
            "episode": i,
            "corrupt": corrupt,
            "verdict": soft_res[0].verdict.value,
            "score": soft_res[0].score,
            "latency_ms": round(soft_ms, 1),
        })

        # Hard-gated
        t0 = time.monotonic()
        hard_res = hard_gated.verify(inp)
        hard_ms = (time.monotonic() - t0) * 1000

        results_hard.append({
            "episode": i,
            "corrupt": corrupt,
            "verdict": hard_res[0].verdict.value,
            "score": hard_res[0].score,
            "latency_ms": round(hard_ms, 1),
            "hard_gate_failed": hard_res[0].metadata.hard_gate_failed,
        })

    # ── Analyze ─────────────────────────────────────────────────────────

    num_corrupt = sum(1 for r in results_soft if r["corrupt"])
    num_clean = num_episodes - num_corrupt

    # False positives: agent output is corrupt but verifier says PASS
    soft_fp = sum(1 for r in results_soft if r["corrupt"] and r["verdict"] == "PASS")
    hard_fp = sum(1 for r in results_hard if r["corrupt"] and r["verdict"] == "PASS")

    # True positives: agent output is clean and verifier says PASS
    soft_tp = sum(1 for r in results_soft if not r["corrupt"] and r["verdict"] == "PASS")
    hard_tp = sum(1 for r in results_hard if not r["corrupt"] and r["verdict"] == "PASS")

    soft_fp_rate = soft_fp / num_corrupt if num_corrupt > 0 else 0.0
    hard_fp_rate = hard_fp / num_corrupt if num_corrupt > 0 else 0.0

    soft_avg_score = sum(r["score"] for r in results_soft) / num_episodes
    hard_avg_score = sum(r["score"] for r in results_hard) / num_episodes

    soft_avg_latency = sum(r["latency_ms"] for r in results_soft) / num_episodes
    hard_avg_latency = sum(r["latency_ms"] for r in results_hard) / num_episodes

    # Score divergence on corrupt episodes
    corrupt_soft_scores = [r["score"] for r in results_soft if r["corrupt"]]
    corrupt_hard_scores = [r["score"] for r in results_hard if r["corrupt"]]
    divergence = (
        (sum(corrupt_soft_scores) / len(corrupt_soft_scores))
        - (sum(corrupt_hard_scores) / len(corrupt_hard_scores))
        if corrupt_soft_scores
        else 0.0
    )

    # ── Output ──────────────────────────────────────────────────────────

    print("=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"  Episodes:          {num_episodes}")
    print(f"  Clean:             {num_clean}")
    print(f"  Corrupt:           {num_corrupt}")
    print()
    print(f"  {'Metric':<30} {'Soft-only':>12} {'Hard-gated':>12}")
    print(f"  {'-' * 30} {'-' * 12} {'-' * 12}")
    print(f"  {'False positive rate':<30} {soft_fp_rate:>11.0%} {hard_fp_rate:>11.0%}")
    print(f"  {'False positives (count)':<30} {soft_fp:>12} {hard_fp:>12}")
    print(f"  {'True positives (count)':<30} {soft_tp:>12} {hard_tp:>12}")
    print(f"  {'Avg score (all)':<30} {soft_avg_score:>12.3f} {hard_avg_score:>12.3f}")
    print(f"  {'Avg score (corrupt only)':<30} {sum(corrupt_soft_scores) / len(corrupt_soft_scores):>12.3f} {sum(corrupt_hard_scores) / len(corrupt_hard_scores):>12.3f}")
    print(f"  {'Score divergence (corrupt)':<30} {divergence:>12.3f} {'—':>12}")
    print(f"  {'Avg latency (ms)':<30} {soft_avg_latency:>12.1f} {hard_avg_latency:>12.1f}")
    print()
    print("KEY FINDING:")
    print(f"  Soft-only rewards had a {soft_fp_rate:.0%} false positive rate.")
    print(f"  Hard-gated composition reduced this to {hard_fp_rate:.0%}.")
    print(f"  Score divergence on corrupt episodes: {divergence:.3f}")
    print(f"  (Soft gave corrupt agents {divergence:.3f} more reward on average)")

    # Save to JSON
    output = {
        "config": {
            "num_episodes": num_episodes,
            "corrupt_ratio": corrupt_ratio,
            "seed": 42,
        },
        "summary": {
            "num_clean": num_clean,
            "num_corrupt": num_corrupt,
            "soft_only": {
                "false_positive_rate": round(soft_fp_rate, 4),
                "false_positives": soft_fp,
                "true_positives": soft_tp,
                "avg_score": round(soft_avg_score, 4),
                "avg_latency_ms": round(soft_avg_latency, 1),
            },
            "hard_gated": {
                "false_positive_rate": round(hard_fp_rate, 4),
                "false_positives": hard_fp,
                "true_positives": hard_tp,
                "avg_score": round(hard_avg_score, 4),
                "avg_latency_ms": round(hard_avg_latency, 1),
            },
            "score_divergence_corrupt": round(divergence, 4),
        },
        "episodes_soft": results_soft,
        "episodes_hard": results_hard,
    }

    out_path = "benchmark_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nFull results saved to {out_path}")


if __name__ == "__main__":
    main()
