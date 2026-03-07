"""MCP server adapter for vr.dev — exposes verifiers as Model Context Protocol tools.

Requires the ``mcp`` optional dependency: ``pip install vrdev[mcp]``

Tools exposed:
  - ``list_verifiers``    — List all registered verifier IDs
  - ``run_verifier``      — Run a verifier with given input
  - ``compose_chain``     — Run a composed chain of verifiers
  - ``explain_failure``   — Explain why a verification failed
  - ``search_verifiers``  — Search verifiers by keyword

Transport: stdio (for Claude Desktop / Cursor integration)
"""

from __future__ import annotations

import json
from typing import Any


def _require_mcp():
    """Import and return the mcp module, raising a clear error if missing."""
    try:
        import mcp  # noqa: F811
        from mcp.server.fastmcp import FastMCP
        return FastMCP
    except ImportError:
        raise ImportError(
            "MCP support requires the 'mcp' package. "
            "Install with: pip install vrdev[mcp]"
        ) from None


def create_mcp_server() -> Any:
    """Create and configure the vr.dev MCP server with all tools registered."""
    FastMCP = _require_mcp()

    mcp = FastMCP(
        "vr.dev",
        version="0.3.0",
        description="Verifiable Rewards for Real-World AI Agent Tasks",
    )

    # ── Tool: list_verifiers ─────────────────────────────────────────

    @mcp.tool()
    def list_verifiers() -> str:
        """List all registered verifier IDs.

        Returns a JSON array of verifier ID strings.
        """
        from vrdev.core.registry import list_verifiers as _list

        return json.dumps(_list(), indent=2)

    # ── Tool: run_verifier ───────────────────────────────────────────

    @mcp.tool()
    def run_verifier(
        verifier_id: str,
        completions: list[str],
        ground_truth: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Run a single verifier against agent completions.

        Args:
            verifier_id: The verifier registry ID (e.g. "vr/filesystem.file_created")
            completions: List of agent completion strings to verify
            ground_truth: Expected outcome dict for the verifier
            context: Optional runtime context (API URLs, configs, etc.)

        Returns:
            JSON array of VerificationResult objects.
        """
        from vrdev.core.registry import get_verifier
        from vrdev.core.types import VerifierInput

        v = get_verifier(verifier_id)
        inp = VerifierInput(
            completions=completions,
            ground_truth=ground_truth or {},
            context=context,
        )
        results = v.verify(inp)
        return json.dumps(
            [r.model_dump(mode="json") for r in results],
            indent=2,
        )

    # ── Tool: compose_chain ──────────────────────────────────────────

    @mcp.tool()
    def compose_chain(
        verifier_ids: list[str],
        completions: list[str],
        ground_truth: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        policy: str = "fail_closed",
    ) -> str:
        """Run a composed chain of verifiers (AND logic by default).

        Args:
            verifier_ids: Ordered list of verifier IDs to compose
            completions: Agent completions
            ground_truth: Shared ground truth dict
            context: Shared runtime context
            policy: "fail_closed" or "fail_open"

        Returns:
            JSON array of composed VerificationResult objects.
        """
        from vrdev.core.compose import compose
        from vrdev.core.registry import get_verifier
        from vrdev.core.types import PolicyMode, VerifierInput

        verifiers = [get_verifier(vid) for vid in verifier_ids]
        mode = PolicyMode(policy)
        composed = compose(verifiers, policy_mode=mode)
        inp = VerifierInput(
            completions=completions,
            ground_truth=ground_truth or {},
            context=context,
        )
        results = composed.verify(inp)
        return json.dumps(
            [r.model_dump(mode="json") for r in results],
            indent=2,
        )

    # ── Tool: explain_failure ────────────────────────────────────────

    @mcp.tool()
    def explain_failure(
        verifier_id: str,
        completions: list[str],
        ground_truth: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Run a verifier and return a human-readable failure explanation.

        Args:
            verifier_id: The verifier registry ID
            completions: Agent completions to verify
            ground_truth: Expected outcome
            context: Runtime context

        Returns:
            Markdown-formatted explanation of the verification result.
        """
        from vrdev.core.registry import get_verifier
        from vrdev.core.types import VerifierInput

        v = get_verifier(verifier_id)
        inp = VerifierInput(
            completions=completions,
            ground_truth=ground_truth or {},
            context=context,
        )
        results = v.verify(inp)

        lines = [f"## Verification: {verifier_id}\n"]
        for i, r in enumerate(results):
            lines.append(f"### Completion {i + 1}")
            lines.append(f"- **Verdict**: {r.verdict.value}")
            lines.append(f"- **Score**: {r.score:.4f}")
            lines.append(f"- **Tier**: {r.tier.value}")
            if r.breakdown:
                lines.append("- **Breakdown**:")
                for k, v_val in r.breakdown.items():
                    lines.append(f"  - {k}: {v_val}")
            if r.evidence:
                lines.append("- **Evidence** (key excerpts):")
                for k, v_val in list(r.evidence.items())[:10]:
                    val_str = str(v_val)[:200]
                    lines.append(f"  - {k}: {val_str}")
            if r.verdict.value != "PASS":
                lines.append("\n**Why it failed**: Check the breakdown scores — "
                            "any sub-check at 0.0 indicates the specific failure point.")
            lines.append("")

        return "\n".join(lines)

    # ── Tool: search_verifiers ───────────────────────────────────────

    @mcp.tool()
    def search_verifiers(query: str) -> str:
        """Search verifiers by keyword.

        Args:
            query: Space-separated keywords to match against verifier IDs

        Returns:
            JSON array of matching verifier ID strings.
        """
        from vrdev.core.registry_loader import search_verifiers as _search

        return json.dumps(_search(query), indent=2)

    # ── Tool: gem_reward ─────────────────────────────────────────────

    @mcp.tool()
    def gem_reward(
        verifier_id: str,
        response: str,
        reference: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Compute a GEM-compatible reward for a single agent response.

        Uses the GEMRewardWrapper adapter to produce a reward dict
        with ``score`` and ``metadata`` fields.

        Args:
            verifier_id: The verifier registry ID
            response: The agent response string to evaluate
            reference: Ground truth / reference dict
            context: Optional runtime context

        Returns:
            JSON reward object: {"score": float, "metadata": dict}
        """
        from vrdev.adapters.gem import GEMRewardWrapper
        from vrdev.core.registry import get_verifier

        v = get_verifier(verifier_id)
        wrapper = GEMRewardWrapper(v)
        result = wrapper.compute_reward(
            response=response,
            reference=reference or {},
            context=context,
        )
        return json.dumps(result, indent=2, default=str)

    return mcp


def run_stdio():
    """Run the MCP server on stdio transport."""
    server = create_mcp_server()
    server.run(transport="stdio")
