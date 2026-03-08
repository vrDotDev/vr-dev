#!/usr/bin/env python3
"""End-to-end smoke test for vr.dev v1.0.0 launch readiness.

Checks:
  1. SDK importable and version correct
  2. All 30 verifiers loadable from registry
  3. CLI entry point responds
  4. Composition engine works
  5. Registry validation passes (0 errors)

Usage:
    cd vr-dev
    python scripts/smoke_test.py
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

EXPECTED_VERSION = "1.0.0"
EXPECTED_VERIFIER_COUNT = 38

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

failures = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  {PASS} {label}")
    else:
        msg = f"{label}: {detail}" if detail else label
        print(f"  {FAIL} {msg}")
        failures.append(msg)


def main():
    print("\n=== vr.dev v1.0.0 Smoke Test ===\n")

    # ── 1. SDK import & version ──────────────────────────────────
    print("[1/5] SDK import & version")
    try:
        import vrdev
        check("vrdev importable", True)
        check(
            f"version == {EXPECTED_VERSION}",
            vrdev.__version__ == EXPECTED_VERSION,
            f"got {vrdev.__version__}",
        )
    except ImportError as e:
        check("vrdev importable", False, str(e))

    # ── 2. Registry: all 30 verifiers loadable ───────────────────
    print("\n[2/5] Registry — load all verifiers")
    try:
        from vrdev.core.registry import list_verifiers, get_verifier

        ids = list_verifiers()
        check(
            f"list_verifiers() returns {EXPECTED_VERIFIER_COUNT}",
            len(ids) == EXPECTED_VERIFIER_COUNT,
            f"got {len(ids)}",
        )

        load_ok = 0
        for vid in ids:
            try:
                v = get_verifier(vid)
                if v is not None:
                    load_ok += 1
            except Exception as e:
                check(f"load {vid}", False, str(e))

        check(
            f"all {EXPECTED_VERIFIER_COUNT} verifiers instantiate",
            load_ok == EXPECTED_VERIFIER_COUNT,
            f"only {load_ok}/{EXPECTED_VERIFIER_COUNT} loaded",
        )
    except ImportError as e:
        check("registry importable", False, str(e))

    # ── 3. CLI entry point ───────────────────────────────────────
    print("\n[3/5] CLI entry point")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "vrdev.cli.main", "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        check(
            "vr --help exits 0",
            result.returncode == 0,
            f"exit {result.returncode}: {result.stderr[:200]}",
        )
    except FileNotFoundError:
        check("vr CLI found", False, "vrdev.cli.main not found")
    except subprocess.TimeoutExpired:
        check("vr --help", False, "timed out after 15s")

    # ── 4. Composition engine ────────────────────────────────────
    print("\n[4/5] Composition engine")
    try:
        from vrdev.core.compose import compose

        check("compose() importable", True)
    except ImportError as e:
        check("compose importable", False, str(e))

    # ── 5. Registry JSON validation ──────────────────────────────
    print("\n[5/5] Registry VERIFIER.json validation")
    registry_dir = Path(__file__).resolve().parent.parent / "registry" / "verifiers"
    if registry_dir.is_dir():
        verifier_dirs = sorted(
            d for d in registry_dir.iterdir() if d.is_dir() and (d / "VERIFIER.json").exists()
        )
        check(
            f"registry has {EXPECTED_VERIFIER_COUNT} verifier dirs",
            len(verifier_dirs) == EXPECTED_VERIFIER_COUNT,
            f"found {len(verifier_dirs)}",
        )

        json_ok = 0
        for d in verifier_dirs:
            vj = d / "VERIFIER.json"
            try:
                data = json.loads(vj.read_text())
                # basic shape checks
                assert "id" in data
                assert "tier" in data
                assert data["tier"] in ("HARD", "SOFT", "AGENTIC")
                json_ok += 1
            except Exception as e:
                check(f"  {d.name}/VERIFIER.json", False, str(e))

        check(
            f"all {len(verifier_dirs)} VERIFIER.json files valid",
            json_ok == len(verifier_dirs),
            f"only {json_ok}/{len(verifier_dirs)} valid",
        )

        # Check fixture files
        fixture_ok = 0
        for d in verifier_dirs:
            for fname in ("positive.json", "negative.json", "adversarial.json"):
                fp = d / fname
                if fp.exists():
                    try:
                        data = json.loads(fp.read_text())
                        # Fixtures can be a bare list or {description, fixtures}
                        items = data if isinstance(data, list) else data.get("fixtures", [])
                        assert isinstance(items, list), f"expected list, got {type(items).__name__}"
                        assert len(items) >= 3, f"minItems 3, got {len(items)}"
                        fixture_ok += 1
                    except Exception as e:
                        check(f"  {d.name}/{fname}", False, str(e))

        expected_fixtures = len(verifier_dirs) * 3
        check(
            f"all {expected_fixtures} fixture files valid (≥3 items each)",
            fixture_ok == expected_fixtures,
            f"only {fixture_ok}/{expected_fixtures} valid",
        )
    else:
        check("registry dir exists", False, str(registry_dir))

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 40)
    if failures:
        print(f"\033[31m{len(failures)} FAILURE(S):\033[0m")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print(f"\033[32mAll checks passed. vr.dev v{EXPECTED_VERSION} is launch-ready.\033[0m")
        sys.exit(0)


if __name__ == "__main__":
    main()
