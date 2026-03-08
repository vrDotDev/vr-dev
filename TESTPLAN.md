# vr.dev Test Plan

Validation checklist for a non-ML-researcher founder. Run these before any release.

## Layer 1: SDK Unit Tests

```bash
cd packages/vrdev
pip install -e ".[dev]"
pytest -v --tb=short
```

**Pass criteria**: All tests green, no skips on core verifiers.

## Layer 2: Smoke Test (Registry Integrity)

```bash
cd scripts
python smoke_test.py
```

Validates every `VERIFIER.json` in the registry: schema conformance, fixture files exist, tier is valid.

## Layer 3: Fixture Tests (Per-Verifier)

```bash
vr test --all
vr test --verifier code.python.tests_pass --type adversarial
```

Each verifier has 3 fixture types:
- **Positive**: Should pass
- **Negative**: Should fail
- **Adversarial**: Edge cases that attempt to fool the verifier

## Layer 4: Composition Engine

```bash
pytest packages/vrdev/tests/test_compose.py -v
```

Tests `fail_closed`, `first_pass`, and gate logic across tiers.

## Layer 5: API Integration

```bash
cd packages/vr-api
pytest tests/ -v
```

Tests the FastAPI endpoints: `/v1/verify`, `/v1/compose`, `/v1/registry`, error codes, auth.

## Layer 6: Evidence Chain

```bash
pytest packages/vrdev/tests/test_evidence.py -v
```

Verifies SHA-256 Merkle chain integrity and Ed25519 signature validation.

## Layer 7: Frontend Build

```bash
cd vrdev
npm run build
```

**Pass criteria**: No TypeScript errors, no build failures.

## Layer 8: Demo Scripts

```bash
cd demos
python demo_code_agent.py
python demo_support_ops.py
python benchmark_gating.py
```

These exercise real end-to-end flows and print results to stdout.

## Layer 9: Registry Validation

```bash
python scripts/validate_registry.py
python scripts/gen_registry.py --check
```

Ensures source registry and frontend registry.json are in sync.

## Quick Smoke (< 2 min)

For fast iteration, run layers 1 + 2 + 7:

```bash
cd packages/vrdev && pytest -x -q && cd ../../scripts && python smoke_test.py && cd ../vrdev && npm run build
```
