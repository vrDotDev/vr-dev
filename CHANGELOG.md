# Changelog

All notable changes to the `vrdev` package will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-09

### Added

- **Verifier Registry**: 38 verifiers across 19 domains (airline, aiv, API, CI, code, cross-domain, database, document, email, filesystem, git, messaging, NLP, payment, project, retail, rubric, tau2, web)
- **Three verification tiers**: HARD (deterministic state checks), SOFT (rubric-based LLM judges), AGENTIC (agent-driven probing)
- **Composition engine**: Chain verifiers into reward pipelines with `policy_mode=FAIL_CLOSED` to gate soft scores behind hard checks
- **BYOS (Bring Your Own State)**: Pass `pre_result` to skip redundant execution — sub-millisecond overhead for RL training loops
- **Evidence system**: Every verification returns structured evidence payloads with raw data, verdict, score, and timestamp
- **Training export**: Native export to TRL, VERL, and OpenClaw formats
- **CLI tool** (`vr`): verify, list, search, test, compose, config, generate commands
- **MCP Server**: 6 tools for Claude Desktop and Cursor integration (`pip install vrdev[mcp]`)
- **Async API**: Full async support via `AsyncVerifier` and `async_compose`
- **Hosted API**: Evidence signing (Ed25519), Merkle chain integrity (SHA-256), optional on-chain anchoring (Base L2)
- **Adversarial fixtures**: Every verifier ships with positive, negative, and adversarial test cases
- **342+ test fixtures** across the registry
- **820+ SDK tests** with 85% coverage enforced in CI
