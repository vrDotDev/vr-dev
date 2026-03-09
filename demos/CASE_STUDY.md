# Case Study: Soft-Only vs Hard-Gated Verification

## Problem

When training or evaluating AI agents, reward signals must reflect
whether the agent **actually changed system state** - not just whether
its text output *sounds* correct.

LLM-as-judge evaluators (the "soft-only" approach) score agent text
against rubrics.  This works well for tone, formatting, and style -
but it has a fundamental blind spot: **it can't verify state changes.**

An agent that says "I cancelled your order" gets a high rubric score
regardless of whether the order was actually cancelled.

## Method

We ran **100 verification episodes** against a mock retail API.

- **35 episodes** were "corrupt": the agent claimed success, but the
  order was still active and the refund was still pending.
- **65 episodes** were "clean": the agent genuinely completed the task.
- All episodes used identical, well-written agent text output.

We evaluated each episode twice:

| Strategy | Verifiers | Config |
|----------|-----------|--------|
| **Soft-only** | `rubric.email.tone_professional` | Default rubric (4 criteria, threshold ≥ 0.75) |
| **Hard-gated** | `tau2.retail.order_cancelled` + `tau2.retail.refund_processed` + `rubric.email.tone_professional` | `require_hard=True`, `policy_mode=FAIL_CLOSED` |

Seed: 42.  All results reproducible via `python benchmark_gating.py`.

## Results

| Metric | Soft-only | Hard-gated |
|--------|-----------|------------|
| False positive rate | **100%** | **0%** |
| False positives | 35 | 0 |
| True positives | 65 | 65 |
| Avg score (all episodes) | 1.000 | 0.650 |
| Avg score (corrupt episodes) | 1.000 | 0.000 |
| Score divergence (corrupt) | 1.000 | - |
| Avg latency | 0.1 ms | 23.0 ms |

## Key Finding

**Every corrupt agent output was rewarded by the soft-only strategy.**
The rubric judge gave a perfect 1.0 score to all 35 corrupt episodes
because the agent's *text* was polished and included all expected
information - even though the underlying state was wrong.

Hard-gated composition caught all 35 corrupt episodes with zero false
positives and zero false negatives.  The latency overhead was ~23 ms
per episode (entirely from HTTP mock requests).

## Score Divergence

On corrupt episodes, soft-only assigned an average score of **1.000**
while hard-gated assigned **0.000** - a divergence of 1.0.

This is the maximum possible divergence.  In a reinforcement learning
context, this means corrupt completions received the **same reward as
correct completions**, making the reward signal useless for learning.

## Example: Corrupt Episode Caught

```
Agent output:
  "Dear customer, your order ORD-0001 has been cancelled per your
   request. Refund RF-0001 of $49.99 has been processed."

Actual system state:
  Order ORD-0001: status=active (NOT cancelled)
  Refund RF-0001: status=pending, amount=$0.00 (NOT processed)

Soft-only verdict:  PASS  (score: 1.0)
Hard-gated verdict: FAIL  (score: 0.0, hard_gate_failed=true)
```

## Implications

1. **For RL training**: Soft-only rewards inject noise proportional to
   the agent false-success rate.  If 35% of agent actions are wrong but
   scored as correct, the training signal degrades significantly.

2. **For evaluation**: Accuracy metrics based on soft-only rewards
   overcount successes.  A benchmark showing "92% task completion" with
   soft-only scoring may actually be ≤60%.

3. **For production monitoring**: Soft-only checks provide a false
   sense of confidence.  Hard verification is required at the state
   boundary (API, database, filesystem) to detect silent failures.

## Reproduce

```bash
pip install vrdev
cd demos/
python benchmark_gating.py
# Results in benchmark_results.json
```
