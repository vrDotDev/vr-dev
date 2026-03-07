"""Composition engine: combine multiple verifiers with hard gating and weighted scoring."""

from __future__ import annotations

from datetime import datetime, timezone

from .base import BaseVerifier
from .types import (
    AttackResistance,
    PolicyMode,
    Provenance,
    ResultMetadata,
    Tier,
    VerificationResult,
    Verdict,
    VerifierInput,
)


class ComposedVerifier(BaseVerifier):
    """Composes multiple verifiers with optional hard gating.

    The composition pipeline:
    1. All component verifiers run.
    2. If ``require_hard=True``: check HARD verifiers first.
       - Any HARD returns FAIL → composed score = 0.0 (hard gate triggered).
       - In ``fail_closed``: ERROR/UNVERIFIABLE also triggers gate.
       - In ``fail_open``: only FAIL triggers gate.
    3. Apply per-verifier weights (default 1.0).
    4. Compute weighted average for final score.
    5. Merge all evidence objects under their verifier ID.
    6. Return composed ``VerificationResult`` with flattened breakdown.
    """

    def __init__(
        self,
        verifiers: list[BaseVerifier],
        require_hard: bool = False,
        weights: dict[str, float] | None = None,
        policy_mode: PolicyMode = PolicyMode.FAIL_CLOSED,
    ):
        self.verifiers = verifiers
        self.require_hard = require_hard
        self.weights = weights or {}
        self.policy_mode = policy_mode

        self.name = "composed/" + "+".join(v.name for v in verifiers) if verifiers else "composed/empty"
        self.version = "0.1.0"

        # Tier inherits the "highest" tier present
        if any(v.tier == Tier.AGENTIC for v in verifiers):
            self.tier = Tier.AGENTIC
        elif any(v.tier == Tier.SOFT for v in verifiers):
            self.tier = Tier.SOFT
        else:
            self.tier = Tier.HARD

    def verify(self, input_data: VerifierInput) -> list[VerificationResult]:
        """Run all component verifiers and merge results per completion."""
        # Collect results from each verifier
        all_results: list[list[VerificationResult]] = []
        for v in self.verifiers:
            all_results.append(v.verify(input_data))

        num_completions = len(input_data.completions)
        composed: list[VerificationResult] = []

        for i in range(num_completions):
            completion_results = [
                results[i] for results in all_results if i < len(results)
            ]
            composed.append(self._merge_results(completion_results, input_data))

        return composed

    def _merge_results(
        self,
        results: list[VerificationResult],
        input_data: VerifierInput,
    ) -> VerificationResult:
        """Merge multiple verification results into a single composed result."""
        # --- Handle empty verifier list ---
        if not results:
            result = VerificationResult(
                verdict=Verdict.UNVERIFIABLE,
                score=0.0,
                tier=self.tier,
                provenance=Provenance(
                    verifier_pkg=self.pkg_id,
                    source_citation="composed",
                    trace_id=(input_data.context or {}).get("trace_id"),
                ),
                metadata=ResultMetadata(policy_mode=self.policy_mode),
            )
            result.compute_hashes(input_data.model_dump())
            return result

        # --- Separate gate tiers (HARD + AGENTIC gate SOFT) ---
        gate_results = [r for r in results if r.tier in (Tier.HARD, Tier.AGENTIC)]

        # --- Check hard gate ---
        hard_gate_failed = False
        if self.require_hard and gate_results:
            for r in gate_results:
                if r.verdict == Verdict.FAIL:
                    hard_gate_failed = True
                    break
                if (
                    self.policy_mode == PolicyMode.FAIL_CLOSED
                    and r.verdict in (Verdict.ERROR, Verdict.UNVERIFIABLE)
                ):
                    hard_gate_failed = True
                    break

        # --- Merge evidence ---
        merged_evidence: dict = {}
        for r in results:
            merged_evidence.update(r.evidence)

        # --- Merge step_rewards ---
        merged_step_rewards: list[float] | None = None
        for r in results:
            if r.step_rewards is not None:
                if merged_step_rewards is None:
                    merged_step_rewards = []
                merged_step_rewards.extend(r.step_rewards)

        # --- Merge breakdown (prefix with verifier pkg) ---
        merged_breakdown: dict[str, float] = {}
        for r in results:
            for k, v in r.breakdown.items():
                merged_breakdown[f"{r.provenance.verifier_pkg}/{k}"] = v

        # --- Compute score ---
        if hard_gate_failed:
            final_score = 0.0
            final_verdict = Verdict.FAIL
        else:
            # Determine which results are scoreable
            scoreable: list[VerificationResult] = []
            for r in results:
                if r.verdict in (Verdict.PASS, Verdict.FAIL):
                    scoreable.append(r)
                elif self.policy_mode == PolicyMode.FAIL_CLOSED:
                    # ERROR/UNVERIFIABLE count as 0 in fail_closed
                    scoreable.append(r)
                # In fail_open, skip ERROR/UNVERIFIABLE

            if not scoreable:
                final_score = 0.0
                final_verdict = Verdict.UNVERIFIABLE
            else:
                total_weight = 0.0
                weighted_score = 0.0
                for r in scoreable:
                    w = self.weights.get(r.provenance.verifier_pkg, 1.0)
                    weighted_score += r.score * w
                    total_weight += w

                final_score = weighted_score / total_weight if total_weight > 0 else 0.0

                # Determine composed verdict
                if all(r.verdict == Verdict.PASS for r in results):
                    final_verdict = Verdict.PASS
                elif any(r.verdict == Verdict.ERROR for r in results):
                    final_verdict = Verdict.ERROR
                elif any(r.verdict == Verdict.UNVERIFIABLE for r in results):
                    final_verdict = Verdict.UNVERIFIABLE
                else:
                    final_verdict = Verdict.FAIL if final_score < 0.5 else Verdict.PASS

        # --- Merge attack resistance ---
        injection_check = "passed"
        format_gaming_check = "passed"
        for r in results:
            if r.attack_resistance.injection_check not in ("passed", "not_applicable"):
                injection_check = r.attack_resistance.injection_check
            if r.attack_resistance.format_gaming_check not in ("passed", "not_applicable"):
                format_gaming_check = r.attack_resistance.format_gaming_check

        # --- Build composed result ---
        result = VerificationResult(
            verdict=final_verdict,
            score=round(final_score, 4),
            tier=self.tier,
            breakdown=merged_breakdown,
            evidence=merged_evidence,
            step_rewards=merged_step_rewards,
            provenance=Provenance(
                verifier_pkg=self.pkg_id,
                source_citation="composed",
                trace_id=(input_data.context or {}).get("trace_id"),
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
            ),
            attack_resistance=AttackResistance(
                injection_check=injection_check,
                format_gaming_check=format_gaming_check,
            ),
            metadata=ResultMetadata(
                execution_ms=sum(r.metadata.execution_ms for r in results),
                permissions_used=list(
                    {p for r in results for p in r.metadata.permissions_used}
                ),
                hard_gate_failed=hard_gate_failed,
                runner_version="0.1.0",
                policy_mode=self.policy_mode,
            ),
        )

        result.compute_hashes(input_data.model_dump())
        return result


def compose(
    verifiers: list[BaseVerifier],
    require_hard: bool = False,
    weights: dict[str, float] | None = None,
    policy_mode: PolicyMode = PolicyMode.FAIL_CLOSED,
) -> ComposedVerifier:
    """Create a composed verifier from multiple component verifiers.

    Parameters
    ----------
    verifiers : list[BaseVerifier]
        Component verifiers to compose.
    require_hard : bool
        If True, any HARD verifier returning FAIL zeroes the composed score.
    weights : dict[str, float] | None
        Per-verifier weights keyed by ``pkg_id``. Default 1.0 for all.
    policy_mode : PolicyMode
        How ERROR/UNVERIFIABLE propagate. Default ``fail_closed``.

    Returns
    -------
    ComposedVerifier
        A single verifier that runs all components and merges results.
    """
    return ComposedVerifier(
        verifiers=verifiers,
        require_hard=require_hard,
        weights=weights,
        policy_mode=policy_mode,
    )
