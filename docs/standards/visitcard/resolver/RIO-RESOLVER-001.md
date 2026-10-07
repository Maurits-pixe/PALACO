# RIO-RESOLVER-001
## Discovery-to-Conversation Resolution v0.1

### Status
Draft v0.1

### Last Updated
2026-10-06

### Canonical statement
RIO Resolver transforms discovery identifiers into verifiable PALACO introduction context.

## Reference flow
BLE/NFC/QR discovery
→ discovery identifier
→ resolver lookup
→ provenance/watermerk checks
→ VisitCard retrieval (bounded)
→ RIO entry handshake

## Resolver obligations
- validate identifier format and freshness
- enforce anti-replay controls
- return bounded introduction payload
- attach provenance and validity metadata
- provide deterministic error states

## Result states
- RESOLVED
- NOT_FOUND
- EXPIRED
- REVOKED
- INVALID
- RATE_LIMITED

## User-facing principle
User sees understandable introduction states, not low-level protocol diagnostics.

## Compliance tags
- VISITCARD-PROVENANCE-COMPLIANT
- VISITCARD-INTRO-COMPLIANT
