# Contributing to vr.dev

Thank you for your interest in contributing to **vr.dev** - Verifiable Rewards for Real-World AI Agent Tasks!

## Getting Started

```bash
# Clone and set up
git clone https://github.com/vrDotDev/vrdev.git
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
| **filesystem** | Directory structure matches spec | HARD |
| **git** | Branch merged with no conflicts | HARD |
| **document.markdown** | README has required sections | HARD |
| **api.github** | Issue created with correct labels | AGENTIC |
| **messaging.twilio** | SMS delivered to recipient | AGENTIC |
| **code.python** | Type-checks with mypy | HARD |
| **code.javascript** | ESLint passes with zero errors | HARD |
| **api.openai** | Completion matches expected schema | SOFT |
| **browser** | Page renders expected element | AGENTIC |

To request a verifier without building it yourself, use our [verifier request template](https://github.com/vrDotDev/vrdev/issues/new?template=verifier_request.md).

## Questions?

Open a [Discussion](https://github.com/vrDotDev/vrdev/discussions) or file an issue.
