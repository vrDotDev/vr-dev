# Contributing to vr.dev

Thank you for your interest in contributing to **vr.dev** - Verifiable Rewards for Real-World AI Agent Tasks!

## Getting Started

```bash
# Clone and set up
git clone https://github.com/vrDotDev/vr-dev.git
cd vr-dev/packages/vrdev

# Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# Install in dev mode with all extras
pip install -e ".[dev,all]"

# Verify everything works
python -m pytest --tb=short -q
```

## Development Workflow

1. **Branch** from `main` - use `feat/`, `fix/`, or `docs/` prefixes
2. **Write tests first** - every verifier needs matching pytest tests
3. **Run the suite** - `python -m pytest --tb=short -q`
4. **Lint** - `ruff check src/ tests/`
5. **Open a PR** targeting `main`

## Adding a New Verifier

Each verifier requires **four artifacts**:

### 1. Task Module

Create `src/vrdev/tasks/<domain>/<name>.py`:
- Subclass `BaseVerifier`
- Set `name`, `tier`, `version` class attributes
- Implement `verify(self, input_data: VerifierInput) -> list[VerificationResult]`
- Use `self._make_result(...)` to build results with provenance

### 2. Registry Entry

Add to `_VERIFIER_MAP` in `src/vrdev/core/registry.py`:
```python
"vr/<domain>.<name>": "vrdev.tasks.<domain>.<module>:<ClassName>",
```

### 3. Registry Fixtures

Create `registry/verifiers/<domain>.<name>/`:
- `VERIFIER.json` - metadata, ground truth schema, scorecard
- `positive.json` - fixtures expected to PASS
- `negative.json` - fixtures expected to FAIL
- `adversarial.json` (optional) - injection/gaming test cases

### 4. Tests

Create `tests/test_<name>.py` with:
- Positive scenarios (PASS)
- Negative scenarios (FAIL)
- Edge cases (ERROR, empty input)
- Metadata/evidence checks
- If HTTP-based: add a mock server in `tests/mocks/`

## Verifier Tier Guide

| Tier | Determinism | Runner | Example |
|------|------------|--------|---------|
| **HARD** | Deterministic | Sandbox / HTTP | `filesystem.file_created`, `git.commit_present` |
| **SOFT** | Stochastic (LLM) | LLM Judge | `rubric.email.tone_professional` |
| **AGENTIC** | Deterministic | HTTP / IMAP | `aiv.calendar.event_created` |

## Code Style

- **Python 3.10+** - use `X | Y` union syntax, not `Union[X, Y]`
- **Pydantic v2** models for all data structures
- **Type hints** on all public functions
- **Docstrings** in NumPy style
- Run `ruff check` before submitting

## Testing Guidelines

- Use `tmp_path` for filesystem tests
- Use `StubJudge` for SOFT verifier tests (no real LLM calls)
- Use session-scoped mock HTTP servers for API verifiers
- Use `MockIMAPRunner` for email verifiers
- Target: every verifier has ≥10 test cases

## Ideas for Verifiers

Looking for something to build? Here are high-value verifier ideas we'd love to see:

| Domain | Verifier Idea | Tier |
|--------|--------------|------|
| **cloud.aws** | S3 object exists after upload | HARD |
| **cloud.aws** | Lambda function deployed & invocable | AGENTIC |
| **api.stripe** | Charge succeeded with correct amount | HARD |
| **api.slack** | Message posted to correct channel | AGENTIC |
| **database.postgres** | Migration applied successfully | HARD |

## Verifier Governance

### Quality Gates

Every verifier PR must pass before merge:

1. **≥10 test cases** — positive, negative, edge cases, and at least one adversarial fixture
2. **Ruff clean** — `ruff check` with zero warnings
3. **Registry spec valid** — `python scripts/validate_registry.py` passes
4. **Fixture coverage** — `positive.json`, `negative.json` present; `adversarial.json` strongly encouraged
5. **Maintainer review** — at least one core maintainer approves

### Versioning

Verifiers follow **semver** within the registry:

- **Patch** (0.1.0 → 0.1.1): Bug fixes, fixture additions — backward compatible
- **Minor** (0.1.0 → 0.2.0): New optional fields, expanded ground_truth schema — backward compatible
- **Major** (0.x → 1.0): Breaking changes to input/output contract — requires migration notice

Version is declared in each verifier's `VERIFIER.json` `version` field.

### Deprecation Policy

1. **Deprecation notice** added to `VERIFIER.json` with `deprecated: true` and `deprecated_by` field pointing to the replacement
2. **Minimum 90 days** between deprecation notice and removal
3. **Removal PR** must reference the deprecation notice commit

### Domain Ownership

Each registry domain (e.g., `database.*`, `aiv.*`) has one or more listed maintainers in `CODEOWNERS`. Domain maintainers review PRs for verifiers in their domain and are responsible for cross-verifier consistency within the domain.
| **filesystem** | Directory structure matches spec | HARD |
| **git** | Branch merged with no conflicts | HARD |
| **document.markdown** | README has required sections | HARD |
| **api.github** | Issue created with correct labels | AGENTIC |
| **messaging.twilio** | SMS delivered to recipient | AGENTIC |
| **code.python** | Type-checks with mypy | HARD |
| **code.javascript** | ESLint passes with zero errors | HARD |
| **api.openai** | Completion matches expected schema | SOFT |
| **browser** | Page renders expected element | AGENTIC |

To request a verifier without building it yourself, use our [verifier request template](https://github.com/vrDotDev/vr-dev/issues/new?template=verifier_request.md).

## Questions?

Open a [Discussion](https://github.com/vrDotDev/vr-dev/discussions) or file an issue.
