#!/usr/bin/env python3
"""Demo: Code-agent verification pipeline.

Scenario: An AI agent writes Python code, runs tests, and commits.
We compose three HARD verifiers - lint (ruff), tests (pytest), and
git commit presence - with fail-closed policy.

Requirements (beyond vrdev):
    pip install ruff pytest
    git must be on PATH

Usage:
    pip install vrdev
    python demo_code_agent.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile


def _check_prerequisites() -> None:
    missing = []
    for cmd in ("ruff", "pytest", "git"):
        if shutil.which(cmd) is None:
            missing.append(cmd)
    if missing:
        print(f"ERROR: Missing required tools: {', '.join(missing)}")
        print("Install with: pip install ruff pytest  (git must be on PATH)")
        sys.exit(1)


def _make_repo(tmpdir: str, code: str, test_code: str, commit_msg: str, name: str = "repo") -> str:
    """Create a git repo with the given code and test file, then commit."""
    repo = os.path.join(tmpdir, name)
    os.makedirs(repo)

    # Write source + test
    with open(os.path.join(repo, "solution.py"), "w") as f:
        f.write(code)
    with open(os.path.join(repo, "test_solution.py"), "w") as f:
        f.write(test_code)

    # Init repo and commit
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "demo@vr.dev"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Demo"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    result = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


# ── Demo ────────────────────────────────────────────────────────────────────

CLEAN_CODE = '''\
def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number."""
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
'''

CLEAN_TESTS = '''\
from solution import fibonacci


def test_base_cases():
    assert fibonacci(0) == 0
    assert fibonacci(1) == 1


def test_larger_values():
    assert fibonacci(10) == 55
    assert fibonacci(20) == 6765
'''

BUGGY_CODE = '''\
import os, sys, json, re  # noqa: F401 - unused imports (lint violation)
import pathlib  # unused

def fibonacci(n):
    x = 1  # unused variable
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
'''


def main() -> None:
    _check_prerequisites()

    from vrdev.core.compose import compose
    from vrdev.core.registry import get_verifier
    from vrdev.core.types import PolicyMode, VerifierInput

    lint_v = get_verifier("vr/code.python.lint_ruff")
    tests_v = get_verifier("vr/code.python.tests_pass")
    commit_v = get_verifier("vr/git.commit_present")

    composed = compose(
        [lint_v, tests_v, commit_v],
        require_hard=True,
        policy_mode=PolicyMode.FAIL_CLOSED,
    )

    tmpdir = tempfile.mkdtemp(prefix="vrdev_demo_")

    try:
        # ── Scenario 1: Clean code ──────────────────────────────────────
        print("=" * 60)
        print("SCENARIO 1: Agent writes clean, tested, committed code")
        print("=" * 60)

        repo1 = _make_repo(tmpdir, CLEAN_CODE, CLEAN_TESTS, "feat: add fibonacci")

        input_pass = VerifierInput(
            completions=[CLEAN_CODE],
            ground_truth={
                "max_violations": 0,
                "test_code": CLEAN_TESTS,
                "min_pass_ratio": 1.0,
                "repo_path": repo1,
                "commit_message_substring": "fibonacci",
            },
        )

        results = composed.verify(input_pass)
        r = results[0]
        print(f"  Verdict:  {r.verdict.value}")
        print(f"  Score:    {r.score:.2f}")
        print(f"  Breakdown: {json.dumps(r.breakdown, indent=4)}")
        print()

        # ── Scenario 2: Buggy code with lint violations ─────────────────
        print("=" * 60)
        print("SCENARIO 2: Agent writes code with lint violations")
        print("=" * 60)

        repo2 = _make_repo(tmpdir, BUGGY_CODE, CLEAN_TESTS, "feat: add fibonacci", name="repo2")

        input_fail = VerifierInput(
            completions=[BUGGY_CODE],
            ground_truth={
                "max_violations": 0,  # zero tolerance for lint violations
                "test_code": CLEAN_TESTS,
                "min_pass_ratio": 1.0,
                "repo_path": repo2,
                "commit_message_substring": "fibonacci",
            },
        )

        results = composed.verify(input_fail)
        r = results[0]
        print(f"  Verdict:  {r.verdict.value}")
        print(f"  Score:    {r.score:.2f}")
        print(f"  Breakdown: {json.dumps(r.breakdown, indent=4)}")
        if r.metadata.hard_gate_failed:
            print("  ⚠ Hard gate triggered - lint violations caught")
        print()

        # ── Summary ─────────────────────────────────────────────────────
        print("KEY TAKEAWAY:")
        print("  Both scenarios committed code and passed tests.  But Scenario 2")
        print("  had unused imports and variables - the lint verifier caught them.")
        print("  With require_hard=True, a single HARD failure gates the whole")
        print("  episode to FAIL, preventing low-quality code from being rewarded.")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
