# RIO-GLOSSARY-001
## Terminology & Canonical Definitions v0.2

### Status
Draft v0.2

### Last Updated
2026-10-06

## A. Core Terms

### RIO
Human-facing communication platform of PALACO across surfaces.

### Surface
A user-facing runtime/channel where RIO is rendered (mobile, web, ELIXER client).

### Conversation
First-class PALACO object containing participants, timeline, context, and governance references.

### Participant
An identity-bearing actor in a conversation (PERSON, CITADEL, WORLD, ELIXER, SYSTEM).

### Message
A communicative unit in a conversation timeline.  
**Message does not imply authority or execution.**

### IntentAction
Structured proposal for a potentially executable action derived from user/system intent and routed through policy/TRIAS.

### Provenance
Origin and transformation lineage metadata for events/messages/intents.

### Evidence
Policy-relevant trace artifacts linked to conversation and action flow.

### Traceability
Ability to reconstruct what happened, by whom, when, and through which decision path.

### Authorization
Explicit grant to perform bounded action under policy; separate from communication.

### Policy Path
Formal route from intent to decision (validation, TRIAS/policy checks, approval/denial).

---

## B. State Terms

### Connection States
- CONNECTED
- DISCONNECTED
- QUEUED
- SYNCHRONIZING
- CONFLICT_REVIEW

### Conversation States
- PENDING
- ACTIVE
- PAUSED
- ARCHIVED
- REVOKED
- DELETED_VIEW

### Intent States
- PROPOSED
- REVIEW
- APPROVED
- DENIED
- EXPIRED
- EXECUTED

---

## C. Constitutional Distinctions (Normative)

1. Communication ≠ Authority  
2. Message ≠ Action  
3. Discovery ≠ Consent  
4. Presence ≠ Permission  
5. Connected ≠ Authorized

---

## D. Canonical User-Facing Copy (Recommended)

- “You are connected.”
- “You are offline. Messages will be queued.”
- “Syncing conversation…”
- “Action requires approval.”
- “Request denied by policy.”
- “Conversation archived.”

---

## E. Compliance Tags

- RIO-GLOSSARY-COMPLIANT
- RIO-CONSTITUTIONAL-LANGUAGE-COMPLIANT
