---
name: Pull Request
about: Submit a change to vr.dev
---

## Summary

<!-- Brief description of the change -->

## Type

- [ ] New verifier
- [ ] Bug fix
- [ ] Feature
- [ ] Documentation
- [ ] Refactor

## Checklist

- [ ] Tests added/updated (`python -m pytest --tb=short -q` passes)
- [ ] Lint clean (`ruff check src/ tests/`)
- [ ] Registry fixtures added (if new verifier)
- [ ] `VERIFIER.json` with ground truth schema and scorecard
- [ ] `positive.json` and `negative.json` fixture files
- [ ] Registry entry added to `_VERIFIER_MAP` in `core/registry.py`
- [ ] Documentation updated (README, docstrings)

## Verifier Details (if applicable)

| Field | Value |
|-------|-------|
| ID | `vr/...` |
| Tier | HARD / SOFT / AGENTIC |
| Runner | sandbox / http / imap / llm |
| Source Benchmark | |

## Test Results

```
<paste pytest output>
```
