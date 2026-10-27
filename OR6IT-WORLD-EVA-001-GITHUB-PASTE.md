# OR6IT — WORLD-EVA-001

Mundo World / Planet Engine Creator — first PALACO World reference package.

## EVA visual reference

### Status
- **World ID:** WORLD-EVA-001
- **Name:** EVA
- **Class:** PALACO World
- **Citadel binding:** LA-001
- **Constitutional reference:** EVA-LA-001
- **Development engine:** OR6IT
- **Design language:** VORM9EVIN9
- **Communication layer:** RIO
- **Lifecycle state:** DESIGN_DRAFT
- **Execution state:** NOT_AUTHORIZED

> This file is a design/specification package. It is **not** a production deployment, authorization, or claim that EVA is active or physically real.

## Concept

A place of memory, creation, life and proof.

Eva is not a planet. Eva is a promise.

EVA is the first PALACO World reference. OR6IT is responsible for World creation and specification; PALACO constitutional infrastructure remains the governing boundary.

## Structure

```text
THE HORIZON
    ↓
THE GATE
    ↓
THE RING
    ↓
FOUR REGIONS
    ↓
THE CORE
```

- **The Horizon** — the horizon of possibilities and the visual starting point.
- **The Gate** — the arrival and controlled entry boundary.
- **The Ring** — the connection layer around the central structure.
- **The Core** — the heart of EVA; implementation remains subject to validation.

### Four regions

| Region   | Function                 | Boundary                                                              |
|----------|--------------------------|-----------------------------------------------------------------------|
| Memory   | Archive and lineage      | Requires provenance and retention rules                               |
| Creation | Atelier and development  | Simulation/design does not equal authorization                        |
| Life     | Nature and habitation    | Visual design alone makes no safety or real-world claim              |
| Proof    | Verification and provenance | Proof remains distinct from trust, decision and authority          |

### Seven first landmarks

1. **The Horizon** — the vision
2. **The Gate** — the arrival
3. **The Ring** — the connection
4. **The Gardens** — the living space
5. **The Atelier** — the creation space
6. **The Archive** — the memory
7. **The Core** — the essence

## OR6IT responsibility

OR6IT is the Mundo World/Planet Engine Creator. For EVA, its proposed responsibilities are:

- generate and version the World seed;
- produce the identity and design manifest;
- define regions, landmarks and relationships;
- prepare dashboard and visual manifests;
- bind objects to provenance and trace references;
- produce proposals for review, not autonomous activation.

## Boundary contract

```text
DESIGN / SIMULATION
        ≠
CONSTITUTIONAL VALIDITY
        ≠
DECISION
        ≠
AUTHORIZATION
        ≠
EXECUTION
```

OR6IT may design, generate, simulate and specify Worlds. It may not independently:

- create constitutional authority;
- publish or activate a World;
- execute external effects;
- infer authorization from design, simulation or consensus;
- represent a simulated state as verified reality.

Any protected state change requires evidence, provenance, constitutional validation, explicit human decision, authorization and a commit gate.

## Proposed lifecycle

```text
DESIGN_DRAFT
    ↓
PROPOSED
    ↓
EVIDENCE_BOUND
    ↓
CONSTITUTIONALLY_VALIDATED
    ↓
HUMAN_DECISION
    ↓
AUTHORIZED
    ↓
COMMIT_ALLOWED
    ↓
ACTIVE
```

Unknown, conflicting or incomplete conditions fail closed and remain visible.

## Machine-readable manifest

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_version": "OR6IT-WORLD-0.1",
  "object_type": "world_design_manifest",
  "status": "DESIGN_DRAFT",
  "engine": {
    "id": "OR6IT",
    "role": "Mundo World/Planet Engine Creator",
    "authority": "NON_AUTHORITATIVE",
    "may_activate_world": false,
    "may_execute_external_effects": false
  },
  "world": {
    "id": "WORLD-EVA-001",
    "name": "EVA",
    "class": "PALACO_WORLD",
    "sequence": 1,
    "statement": "A place of memory, creation, life and proof. Eva is not a planet. Eva is a promise.",
    "design_language": "VORM9EVIN9",
    "communication_layer": "RIO"
  },
  "citadel": {
    "binding_id": "LA-001",
    "constitutional_reference": "EVA-LA-001"
  },
  "structure": {
    "sequence": [
      "HORIZON",
      "GATE",
      "RING",
      "FOUR_REGIONS",
      "CORE"
    ],
    "regions": [
      {
        "id": "MEMORY",
        "label": "Memory",
        "purpose": "Archive and lineage",
        "verification_state": "UNSPECIFIED"
      },
      {
        "id": "CREATION",
        "label": "Creation",
        "purpose": "Atelier and development",
        "verification_state": "UNSPECIFIED"
      },
      {
        "id": "LIFE",
        "label": "Life",
        "purpose": "Nature and habitation",
        "verification_state": "UNSPECIFIED"
      },
      {
        "id": "PROOF",
        "label": "Proof",
        "purpose": "Verification and provenance",
        "verification_state": "UNSPECIFIED"
      }
    ],
    "landmarks": [
      {
        "id": "THE_HORIZON",
        "label": "The Horizon",
        "meaning": "The vision"
      },
      {
        "id": "THE_GATE",
        "label": "The Gate",
        "meaning": "The arrival"
      },
      {
        "id": "THE_RING",
        "label": "The Ring",
        "meaning": "The connection"
      },
      {
        "id": "THE_GARDENS",
        "label": "The Gardens",
        "meaning": "The living space"
      },
      {
        "id": "THE_ATELIER",
        "label": "The Atelier",
        "meaning": "The creation space"
      },
      {
        "id": "THE_ARCHIVE",
        "label": "The Archive",
        "meaning": "The memory"
      },
      {
        "id": "THE_CORE",
        "label": "The Core",
        "meaning": "The essence"
      }
    ]
  },
  "lifecycle": {
    "design_state": "DESIGN_DRAFT",
    "execution_state": "NOT_AUTHORIZED",
    "activation_requires": [
      "IDENTITY_VALIDATION",
      "PROVENANCE_BINDING",
      "EVIDENCE_POLICY_EVALUATION",
      "CONSTITUTIONAL_VALIDATION",
      "HUMAN_DECISION",
      "EXPLICIT_AUTHORIZATION",
      "COMMIT_GATE"
    ]
  },
  "visual_reference": {
    "path": "assets/world-eva-001-reference.png",
    "type": "CONCEPT_DESIGN_REFERENCE",
    "technical_specification": false,
    "constitutional_authority": false
  },
  "provenance": {
    "source_class": "USER_SUPPLIED_DESIGN_REFERENCE",
    "evidence_state": "DESIGN_EVIDENCE_ONLY",
    "validation_state": "UNVALIDATED"
  }
}
```

## GitHub handoff

### Suggested branch
- `feat/or6it-world-eva-001`

### Suggested repository contents
- `OR6IT-WORLD-EVA-001-GITHUB-PASTE.md`
- `assets/world-eva-001-reference.png`

### Checklist
- [ ] Kies de doelrepository.
- [ ] Plaats de EVA-visual als `assets/world-eva-001-reference.png`.
- [ ] Voeg dit bestand toe.
- [ ] Controleer de JSON-manifest tegen de canonieke repositorieschema’s.
- [ ] Open een draft pull request.
- [ ] Review provenance, evidence en constitutional boundaries.
- [ ] Geen activatie, publicatie of deployment zonder afzonderlijke menselijke autorisatie.

## Open implementation questions

- Wat is het canonieke schema voor een World manifest?
- Hoe resolveert LA-001 naar een concrete Citadel-implementatie?
- Wat is de exacte interface tussen OR6IT en RIO?
- Welke evidence policy valideert een World vóór activatie?
- Welke menselijke rol mag een World commit autoriseren?
