# vrdev Demos

Self-contained demo scripts showing vrdev's verifiable-rewards pipeline.
Each script embeds its own mock server - no external services required.

## Prerequisites

```bash
pip install vrdev
```

**Demo 2 (Code Agent)** also requires `ruff`, `pytest`, and `git` on your PATH.

## Running

```bash
python demo_support_ops.py     # Retail support: cancel → refund → inventory
python demo_code_agent.py      # Code agent: lint → test → commit
python demo_browser_agent.py   # Browser agent: e-commerce order verification
python benchmark_gating.py     # Case study: soft-only vs hard-gated (100 episodes)
```

## What you'll see

Each demo runs **two scenarios**:

1. **PASS** - the agent did its job correctly; all verifiers confirm state changes.
2. **FAIL** - the agent _claimed_ success but hard verifiers catch the lie.

The benchmark script quantifies this across 100 episodes and writes
`benchmark_results.json`.

## Demo descriptions

| Script | Verifiers used | Domain |
|--------|---------------|--------|
| `demo_support_ops.py` | `order_cancelled` + `refund_processed` + `inventory_updated` | τ²-bench retail |
| `demo_code_agent.py` | `lint_ruff` + `tests_pass` + `commit_present` | Code quality |
| `demo_browser_agent.py` | `order_placed` + `refund_processed` | WebArena e-commerce |
| `benchmark_gating.py` | Composed HARD+SOFT across 100 episodes | Cross-domain |
