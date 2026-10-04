# ADR-0002: Communication Does Not Imply Authority

- **Status:** Accepted  
- **Date:** 2026-10-02  
- **Owner:** PALACO Foundation  
- **Deciders:** Constitution / Governance / RIO Architecture

## Context
RIO handles human communication that may include requests with operational impact (e.g., create/update/delete/grant/revoke).  
Without explicit boundaries, conversational text could be misinterpreted as executable authority.

## Decision
PALACO adopts the constitutional rule:

**COMMUNICATION ≠ AUTHORITY**  
**MESSAGE ≠ ACTION**

Any potentially executable request must pass through:
1. intent proposal (`IntentAction`)
2. policy/TRIAS evaluation
3. explicit authorization decision
4. bounded execution
5. trace/evidence registration

## Consequences
### Positive
- Prevents implicit authority escalation
- Improves safety for high-impact operations
- Makes policy and user consent explicit
- Produces auditable decision trails

### Trade-offs
- Additional UX steps for sensitive actions
- Slightly higher interaction latency for execution flows
- Requires robust intent extraction/validation design

## Alternatives Considered
1. **Direct command execution from chat**  
   Rejected: violates constitutional boundary and safety model.
2. **Partial execution with heuristic confirmation**  
   Rejected: ambiguous authority semantics.
3. **Explicit intent-policy-authorization pipeline**  
   Accepted.

## Compliance Impact
Supports:
- RIO-AUTH-BOUNDARY-COMPLIANT
- Constitutional separation controls
- Evidence/traceability obligations

## Links
- `docs/standards/rio/governance/RIO-AUTH-BOUNDARY-001.md`
- `docs/standards/rio/platform/RIO-PLATFORM-001.md`
- `docs/standards/rio/diagrams/RIO-SEQUENCE-DIAGRAMS-001.md`
