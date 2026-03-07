"""Scaffold a new verifier from a template.

Usage::

    vr generate --name "database.row.updated" --tier hard
    vr generate --name "messaging.slack.sent" --tier agentic
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import click


_VERIFY_PY_TEMPLATE = '''\
"""Verifier: {name}

Ground truth schema::

    {{
        "TODO": "define expected fields"
    }}

Context (optional)::

    {{
        "TODO": "define runtime config"
    }}
"""

from __future__ import annotations

import time
from typing import Any

from vrdev.core.base import BaseVerifier
from vrdev.core.types import Tier, Verdict, VerifierInput, VerificationResult


class {class_name}(BaseVerifier):
    """{description}"""

    name = "{name}"
    tier = Tier.{tier_upper}
    version = "0.1.0"

    def verify(self, input_data: VerifierInput) -> list[VerificationResult]:
        gt = input_data.ground_truth
        results: list[VerificationResult] = []

        for completion in input_data.completions:
            start = time.monotonic_ns()
            result = self._verify_single(gt, completion, input_data)
            result.metadata.execution_ms = (time.monotonic_ns() - start) // 1_000_000
            results.append(result)

        return results

    def _verify_single(
        self,
        gt: dict[str, Any],
        completion: str,
        input_data: VerifierInput,
    ) -> VerificationResult:
        evidence: dict[str, Any] = {{}}
        breakdown: dict[str, float] = {{}}

        # TODO: Implement verification logic
        # 1. Extract expected values from gt
        # 2. Check actual system state
        # 3. Populate breakdown and evidence
        # 4. Determine verdict and score

        verdict = Verdict.PASS
        score = 1.0

        return self._make_result(
            verdict, score, breakdown, evidence, input_data,
            permissions=[],
        )
'''

_VERIFIER_JSON_TEMPLATE = {
    "version": "0.1.0",
    "ground_truth_schema": {
        "type": "object",
        "required": [],
        "properties": {},
    },
    "scorecard": {
        "determinism": "deterministic",
        "evidence_quality": "hard-state",
        "intended_use": "eval-and-train",
        "gating_required": False,
        "recommended_gates": [],
        "permissions_required": [],
    },
    "contributor": "vr.dev",
}

_FIXTURE_TEMPLATE = {"fixtures": []}


def _name_to_class(name: str) -> str:
    """Convert 'database.row.updated' to 'RowUpdatedVerifier'."""
    parts = name.split(".")
    # Use the last 2 parts for the class name
    relevant = parts[-2:] if len(parts) >= 2 else parts
    return "".join(p.capitalize() for p in relevant) + "Verifier"


def _name_to_domain(name: str) -> str:
    """Extract domain from name: 'database.row.updated' -> 'database'."""
    return name.split(".")[0]


@click.command()
@click.option(
    "--name", "-n", required=True,
    help="Verifier name (e.g. database.row.updated)",
)
@click.option(
    "--tier", "-t", required=True,
    type=click.Choice(["hard", "soft", "agentic"], case_sensitive=False),
    help="Verifier tier",
)
@click.option(
    "--description", "-d", default="",
    help="Short description of what this verifier checks",
)
@click.option(
    "--output", "-o", default=None, type=click.Path(),
    help="Output directory (default: registry/verifiers/<name>/)",
)
def generate(name: str, tier: str, description: str, output: str | None) -> None:
    """Scaffold a new verifier from a template.

    Creates the directory structure, VERIFIER.json, verify.py template,
    and empty fixture files.
    """
    verifier_id = f"vr/{name}"
    class_name = _name_to_class(name)
    domain = _name_to_domain(name)
    tier_upper = tier.upper()

    if not description:
        description = f"Verifies {name.replace('.', ' ')}"

    # Determine output path
    if output:
        out_dir = Path(output)
    else:
        # Default: relative to the registry directory
        out_dir = Path("registry") / "verifiers" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write VERIFIER.json
    spec = {
        "id": verifier_id,
        **_VERIFIER_JSON_TEMPLATE,
        "tier": tier_upper,
        "domain": domain,
        "task_type": name.split(".")[-1] if "." in name else name,
        "description": description,
        "created_at": date.today().isoformat(),
        "source_citation": "",
        "permissions_required": [],
    }
    spec_path = out_dir / "VERIFIER.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")

    # 2. Write verify.py
    verify_path = out_dir / "verify.py"
    verify_path.write_text(
        _VERIFY_PY_TEMPLATE.format(
            name=name,
            class_name=class_name,
            tier_upper=tier_upper,
            description=description,
        )
    )

    # 3. Write fixture files
    for fixture_name in ("positive", "negative", "adversarial"):
        fixture_path = out_dir / f"{fixture_name}.json"
        fixture_path.write_text(json.dumps(_FIXTURE_TEMPLATE, indent=2) + "\n")

    click.echo(f"✓ Scaffolded verifier: {verifier_id}")
    click.echo(f"  Directory: {out_dir}")
    click.echo(f"  Files created:")
    click.echo(f"    VERIFIER.json   — spec (edit ground_truth_schema)")
    click.echo(f"    verify.py       — implementation (fill in TODO)")
    click.echo(f"    positive.json   — add 3+ passing fixtures")
    click.echo(f"    negative.json   — add 3+ failing fixtures")
    click.echo(f"    adversarial.json — add 3+ adversarial fixtures")
    click.echo()
    click.echo(f"  Next steps:")
    click.echo(f"    1. Edit verify.py — implement _verify_single()")
    click.echo(f"    2. Add to registry.py: \"{verifier_id}\": \"module:{class_name}\"")
    click.echo(f"    3. Add fixture data to positive/negative/adversarial.json")
    click.echo(f"    4. Run: vr registry validate {out_dir}")
