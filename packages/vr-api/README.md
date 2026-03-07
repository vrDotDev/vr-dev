# vr-api — Hosted Verification Service

> **Phase 4**: This service will be built after pilot validation (Phase 2)
> and public launch (Phase 3).

The hosted API wraps the `vrdev` Python SDK in a FastAPI service with:
- Authentication and API key management
- Rate limiting per pricing tier
- Managed runners for Tier C (AGENTIC) verifiers (IMAP, browser, shell sandboxes)
- Immutable evidence log storage for enterprise audit compliance
- Usage tracking for billing

## Architecture Principle

The API layer contains **zero verifier logic**. It wraps `packages/vrdev/` and adds
infrastructure concerns. The same verifier code runs locally (free) and in the cloud
(paid). This ensures parity.

## Pricing Tiers (Planned)

| Tier | Price | Calls/Month | Evidence Retention |
|---|---|---|---|
| Free | $0 | 500 | None |
| Pro | $99-299 | 20,000 | 30 days |
| Team | $499-1,499 | 100,000 | 90 days |
| Enterprise | $8k-25k | Unlimited | Custom SLA |
