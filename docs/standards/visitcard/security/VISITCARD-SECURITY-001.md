# VISITCARD-SECURITY-001
## Security & Threat Model v0.1

### Status
Draft v0.1

### Last Updated
2026-10-06

## Threats
- spoofed beacon identifiers
- replay of stale discovery tokens
- passive tracking via stable IDs
- phishing through deceptive introduction UI

## Controls
1. Rotating discovery IDs
2. Freshness window + anti-replay checks
3. Resolver-side verification and rate limits
4. Provenance binding (watermerk/hologram references)
5. Clear trust indicators in UX

## Security boundary
Beacon is an introduction carrier, not a credential.

## Incident posture
- mark suspicious resolution as INVALID
- avoid auto-upgrade to trusted status
- preserve trace evidence for review

## Compliance tags
- VISITCARD-PROVENANCE-COMPLIANT
- VISITCARD-BEACON-COMPLIANT
