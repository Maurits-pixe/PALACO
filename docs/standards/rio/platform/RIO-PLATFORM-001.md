# RIO-PLATFORM-001
## PALACO RIO Chat-Platform v0.1

### Metadata
Draft v0.1

### Canonical statement
**RIO is the human-facing, cross-surface communication platform of PALACO.**

RIO enables persons, Citadels, Worlds and ELIXERS to communicate across supported surfaces (mobile, web, other clients) while preserving:
- identity
- context
- provenance
- user control
- evidence
- traceability
- constitutional boundaries

### Core principles
1. **Surface Independence**  
   A conversation is not bound to a single device, app, or website.
2. **Conversation as Object**  
   A RIO conversation is a first-class PALACO object with identity and state.
3. **Communication ≠ Authority**  
   A message never implies authorization or execution by itself.
4. **Discoverability of Meaning**  
   VORM9EVING must preserve semantic consistency across surfaces.
5. **Offline Continuity**  
   Temporary disconnection does not imply loss of conversation continuity.
6. **Traceable Interaction**  
   Relevant conversation events are evidence-addressable and time-bounded.

### Platform scope
RIO platform includes:
- conversation object model
- participant model
- message/event model
- cross-surface transport
- sync/offline behavior
- policy boundary for actionable requests
- UX consistency contract

RIO platform excludes:
- automatic authority delegation by message
- implicit execution of irreversible actions from plain chat text

### Constitutional boundary
**RIO SHALL INTRODUCE, CONVEY, AND COORDINATE COMMUNICATION;  
RIO SHALL NOT BY ITSELF GRANT AUTHORITY.**

### Interaction model
DISCOVER → RECOGNIZE → MEET → CONNECT → CONVERSE → (OPTIONAL) INTENT → POLICY/TRIAS → AUTHORIZATION → ACTION

### Required guarantees
- deterministic ordering within a conversation timeline domain
- idempotent delivery semantics for retry paths
- explicit participant identity references
- auditable transitions for moderation/administrative state changes
- reversible presentation state where possible; irreversible actions require explicit policy path

### Compliance labels
- RIO-PLATFORM-COMPLIANT
- RIO-SURFACE-COMPLIANT
- RIO-AUTH-BOUNDARY-COMPLIANT
