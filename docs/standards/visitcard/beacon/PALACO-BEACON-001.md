# PALACO-BEACON-001
## Proximity Discovery Carrier v0.1

### Status
Draft v0.1

### Canonical statement
**PALACO Beacon provides discovery without authority.**

### Purpose
Expose a minimal proximity signal that points to VisitCard/RIO resolution.

### Design rule
Beacon payload remains minimal and privacy-preserving.

### Recommended beacon payload profile
- `P`: protocol family marker (PALACO)
- `V`: version
- `T`: object type
- `D`: discovery identifier (rotating)
- `E`: ephemeral identifier
- `R`: resolver reference

### Explicitly excluded from public beacon payload
- full identity profile
- personal contact data
- full VisitCard object body
- authorization-bearing claims

### Privacy constraints
- rotating identifiers
- bounded broadcast cadence
- anti-tracking posture

### Constitutional boundary
**Discovery ≠ Consent**

### Compliance tags
- VISITCARD-BEACON-COMPLIANT
- VISITCARD-CONSENT-COMPLIANT
