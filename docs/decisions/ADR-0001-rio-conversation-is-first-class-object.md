# ADR-0001: RIO Conversation is a First-Class Object

- **Status:** Accepted  
- **Date:** 2026-10-02  
- **Owner:** PALACO Foundation  
- **Deciders:** Architecture / RIO Governance

## Context
RIO must support communication across multiple surfaces (mobile, web, ELIXER) without fragmenting user experience or conversation meaning.  
If conversation state is tied to a device/session, continuity and traceability break down.

## Decision
A **RIO Conversation** is defined as a **first-class PALACO object** with:
- stable conversation identity
- participant model
- context references
- timeline/events
- provenance/evidence references
- lifecycle state

Conversation identity and semantics are independent of rendering surface.

## Consequences
### Positive
- Seamless cross-surface continuity
- Better auditability and evidence handling
- Cleaner offline/sync model (cursor + event replay)
- Clear separation between UI session and conversation state

### Trade-offs
- Additional backend object lifecycle management
- More explicit schema and versioning requirements
- Requires strict idempotency and ordering controls

## Alternatives Considered
1. **Device-bound chat sessions**  
   Rejected: breaks continuity and governance semantics.
2. **Surface-local conversations with sync bridges**  
   Rejected: duplicate identity domains and conflict complexity.
3. **Conversation as first-class object**  
   Accepted.

## Compliance Impact
Supports:
- RIO-PLATFORM-COMPLIANT
- RIO-SURFACE-COMPLIANT
- RIO traceability requirements

## Links
- `docs/standards/rio/conversation/RIO-CONVERSATION-001.md`
- `docs/standards/rio/sync/RIO-SYNC-001.md`
- `docs/schemas/rio/RIO-SCHEMA-BUNDLE-001.json`
