# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in vr.dev, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

### How to report

Email **security@vr.dev** with:

1. A description of the vulnerability
2. Steps to reproduce
3. The affected component (SDK, hosted API, registry, or CLI)
4. Any potential impact assessment

### What to expect

- **Acknowledgment** within 48 hours
- **Triage and initial assessment** within 5 business days
- **Fix timeline** communicated once severity is assessed
- **Credit** in the release notes (unless you prefer to remain anonymous)

### Scope

| Component | In scope |
|-----------|----------|
| Python SDK (`vrdev` package) | Yes |
| CLI tool (`vr`) | Yes |
| Hosted API (`api.vr.dev`) | Yes |
| Verifier registry logic | Yes |
| Evidence signing / Merkle chain | Yes |
| Frontend (`vr.dev` website) | Yes |
| Third-party dependencies | Report upstream; notify us if exploitable in our context |

### Out of scope

- Social engineering attacks on maintainers
- Denial of service via rate limiting (already handled)
- Vulnerabilities in dependencies with no path to exploitation in vr.dev

## Security Design

The vr.dev security model has three layers:

1. **Auditability** (local SDK + hosted API): Every verification returns structured evidence payloads with the raw data used to make the verdict.

2. **Integrity** (hosted API only): Evidence is Ed25519-signed and content-hashed into a SHA-256 Merkle chain. Signatures are verifiable with the published public key.

3. **Anchoring** (optional, hosted API): Merkle roots are periodically anchored on Base L2 for third-party-verifiable tamper evidence.

Local SDK users get Layer 1 (auditability). Hosted API users get all three layers.
