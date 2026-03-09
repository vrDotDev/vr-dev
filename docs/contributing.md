# Contributing to vr.dev

## Adding a Verifier

1. Fork the repository
2. Copy `registry/verifiers/_template/` to `registry/verifiers/<domain>/<name>/`
3. Fill in `VERIFIER.json` (must validate against `registry/schemas/verifier_spec.json`)
4. Implement the verifier in `packages/vrdev/src/vrdev/tasks/<domain>/<name>.py`
5. Write three fixture sets:
   - `positive.json`: 3+ cases where `verdict=PASS`, `score >= 0.8`
   - `negative.json`: 3+ cases where `verdict=FAIL`, `score <= 0.3`
   - `adversarial.json`: 3+ cheat attempts that must return `verdict=FAIL`
6. Run `vr test <verifier_id>` to confirm all fixtures pass
7. Open a PR - CI will validate automatically

## Adding a Skill

1. Fork the repository
2. Create `registry/skills/<domain>/<name>/SKILL.json`
3. Write fixture sets following the same pattern
4. Skills start as DRAFT and must be promoted through the lifecycle

## Quality Gates (CI)

All PRs must pass:
- `VERIFIER.json` / `SKILL.json` validates against schema
- All positive fixtures return `verdict=PASS` with `score >= 0.8`
- All negative fixtures return `verdict=FAIL` with `score <= 0.3`
- All adversarial fixtures return `verdict=FAIL` regardless of score
