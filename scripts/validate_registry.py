#!/usr/bin/env python3
"""Validate all registry specs and fixture files.

Usage::

    python scripts/validate_registry.py

Returns exit code 0 if all specs are valid, 1 otherwise.
Designed to run in CI as part of the test pipeline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Resolve project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REGISTRY_DIR = PROJECT_ROOT / "registry"
VERIFIERS_DIR = REGISTRY_DIR / "verifiers"
SCHEMAS_DIR = REGISTRY_DIR / "schemas"

# Add vrdev to path for imports
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "vrdev" / "src"))


def load_schema(name: str) -> dict:
    """Load a JSON schema from the schemas directory."""
    path = SCHEMAS_DIR / name
    return json.loads(path.read_text())


def validate_json_schema(data: dict, schema: dict, path: str) -> list[str]:
    """Validate data against a JSON schema. Returns list of error messages."""
    try:
        import jsonschema
    except ImportError:
        return [f"{path}: jsonschema not installed — cannot validate"]

    validator = jsonschema.Draft7Validator(schema)
    return [
        f"{path}: {'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    ]


def main() -> int:
    errors: list[str] = []
    verifier_count = 0
    fixture_count = 0

    # Load schemas
    fixture_schema = load_schema("fixture_spec.json")
    verifier_schema = load_schema("verifier_spec.json")

    # Validate each verifier directory
    for verifier_dir in sorted(VERIFIERS_DIR.iterdir()):
        if not verifier_dir.is_dir() or verifier_dir.name.startswith("."):
            continue

        verifier_id = f"vr/{verifier_dir.name}"

        # Check VERIFIER.json exists
        spec_path = verifier_dir / "VERIFIER.json"
        if not spec_path.exists():
            errors.append(f"{verifier_id}: missing VERIFIER.json")
            continue

        # Validate VERIFIER.json against canonical JSON schema
        try:
            spec_data = json.loads(spec_path.read_text())
            schema_errors = validate_json_schema(
                spec_data, verifier_schema, f"{verifier_id}/VERIFIER.json"
            )
            errors.extend(schema_errors)
            if not schema_errors:
                verifier_count += 1
        except json.JSONDecodeError as exc:
            errors.append(f"{verifier_id}/VERIFIER.json: invalid JSON: {exc}")

        # Validate fixture files
        for fixture_name in ("positive.json", "negative.json", "adversarial.json"):
            fixture_path = verifier_dir / fixture_name
            if not fixture_path.exists():
                errors.append(f"{verifier_id}: missing {fixture_name}")
                continue

            try:
                data = json.loads(fixture_path.read_text())
                # Wrap bare arrays in {"fixtures": ...} for schema compat
                if isinstance(data, list):
                    data = {"fixtures": data}
                schema_errors = validate_json_schema(
                    data, fixture_schema, f"{verifier_id}/{fixture_name}"
                )
                errors.extend(schema_errors)
                if not schema_errors:
                    fixture_count += 1
            except json.JSONDecodeError as exc:
                errors.append(f"{verifier_id}/{fixture_name}: invalid JSON: {exc}")

        # Validate adversarial.json has attack_type on all entries
        adv_path = verifier_dir / "adversarial.json"
        if adv_path.exists():
            try:
                adv_data = json.loads(adv_path.read_text())
                for i, fixture in enumerate(adv_data.get("fixtures", [])):
                    if "attack_type" not in fixture:
                        errors.append(
                            f"{verifier_id}/adversarial.json: fixture[{i}] "
                            f"({fixture.get('name', '?')}) missing attack_type"
                        )
            except (json.JSONDecodeError, KeyError):
                pass  # Already reported above

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Registry Validation Summary")
    print(f"{'=' * 60}")
    print(f"Verifiers validated: {verifier_count}")
    print(f"Fixture files validated: {fixture_count}")
    print(f"Errors found: {len(errors)}")

    if errors:
        print(f"\n{'─' * 60}")
        print("ERRORS:")
        for err in errors:
            print(f"  ✗ {err}")
        print(f"\nValidation FAILED with {len(errors)} error(s).")
        return 1

    print("\n✓ All registry specs and fixtures are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
