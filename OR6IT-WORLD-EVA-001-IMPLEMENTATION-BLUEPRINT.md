# OR6IT — WORLD-EVA-001

## Implementation Blueprint v0.1

### Status

- **Preparation state:** `READY_FOR_IMPLEMENTATION_REVIEW`
- **World:** `WORLD-EVA-001`
- **Citadel binding:** `LA-001`
- **Constitutional reference:** `EVA-LA-001`
- **Engine:** `OR6IT`
- **Runtime activation:** `NOT_AUTHORIZED`
- **External effects:** `FORBIDDEN IN THIS PHASE`

This document prepares implementation work. It does not authorize merge,
activation, deployment, or external-world effects.

## 1. Objective

Build the first read-only, deterministic OR6IT World Engine slice for
`WORLD-EVA-001`.

The first slice must:

- load a versioned World design manifest;
- validate identity, required fields, and internal references;
- produce a deterministic normalized World proposal;
- attach provenance and evidence-state metadata;
- expose EVA structure, regions, and landmarks to a read-only dashboard/API;
- return explicit `UNKNOWN`, `INCOMPLETE`, `CONFLICT`, and `INVALID` states;
- never activate, publish, or execute external effects.

## 2. Non-goals

The first slice must not:

- create constitutional authority;
- infer authorization from a valid manifest;
- write to external systems;
- activate or publish a World;
- claim that EVA is physically real;
- treat a visual asset as technical proof;
- silently resolve conflicting sources;
- replace human review.

## 3. Proposed module boundaries

```text
or6it/
├── manifest/       # schema, parser, normalizer, validator
├── world/          # proposal, regions, landmarks, lifecycle
├── provenance/     # source refs, evidence state, trace
├── gates/          # identity, evidence, constitution, activation
├── adapters/       # EVA and RIO boundaries
└── read-model/     # dashboard and read-only API
```

The exact placement must follow the target repository's existing architecture.
Do not create a parallel runtime if a canonical engine boundary already exists.

## 4. Core contracts

### World proposal

```ts
type WorldProposalState =
  | "DESIGN_DRAFT" | "PROPOSED" | "EVIDENCE_BOUND"
  | "VALIDATED" | "INCOMPLETE" | "CONFLICT"
  | "INVALID" | "UNKNOWN";

type WorldProposal = {
  proposalId: string;
  worldId: "WORLD-EVA-001";
  engineId: "OR6IT";
  manifestVersion: string;
  state: WorldProposalState;
  identity: {
    name: "EVA";
    class: "PALACO_WORLD";
    citadelBinding: "LA-001";
    constitutionalReference: "EVA-LA-001";
  };
  structure: {
    sequence: string[];
    regions: Region[];
    landmarks: Landmark[];
  };
  provenance: ProvenanceState;
  evidence: EvidenceState;
  trace: TraceReference;
};
```

### OR6IT engine boundary

```ts
interface Or6itWorldEngine {
  parse(input: unknown): ParseResult;
  validate(manifest: WorldManifest): ValidationResult;
  normalize(manifest: WorldManifest): NormalizedManifest;
  propose(manifest: WorldManifest): WorldProposal;
  explain(proposal: WorldProposal): EvidencePath;
}
```

There must be no `activate()`, `publish()`, `execute()`, or equivalent method in
this first-slice interface.

### Gate result

```ts
type GateResult =
  | { result: "ALLOW_READ_ONLY"; reasons: string[] }
  | { result: "BLOCKED"; reasons: string[] }
  | { result: "UNKNOWN"; reasons: string[] }
  | { result: "INCOMPLETE"; missing: string[] }
  | { result: "CONFLICT"; conflicts: string[] };
```

`UNKNOWN` must never be coerced to success.

## 5. EVA fixture

The first fixture is the supplied `WORLD-EVA-001` design manifest:

- **Structure:** `HORIZON → GATE → RING → FOUR_REGIONS → CORE`
- **Regions:** `MEMORY`, `CREATION`, `LIFE`, `PROOF`
- **Landmarks:** `THE_HORIZON`, `THE_GATE`, `THE_RING`, `THE_GARDENS`,
  `THE_ATELIER`, `THE_ARCHIVE`, `THE_CORE`
- **Communication layer:** `RIO`
- **Design language:** `VORM9EVIN9`
- **Visual reference:** `assets/world-eva-001-reference.png`

The fixture is synthetic design evidence. It is not production data and not
proof of constitutional validity.

## 6. Validation rules

### Identity

- World ID is present and immutable within the manifest version.
- World name and class are present.
- Citadel binding and constitutional reference are explicit.
- OR6IT is recorded as creator/development engine, not authority.

### Structure

- All five structural layers are present and ordered.
- Exactly four regions are present in the first EVA fixture.
- Each landmark has a stable identifier and meaning.
- Duplicate IDs are rejected.
- Broken references are `INVALID` or `INCOMPLETE`, never silently repaired.

### Provenance

- Every imported design asset has a source reference.
- Visual assets are labeled `CONCEPT_DESIGN_REFERENCE`.
- A source reference does not become authorization.
- Missing provenance blocks constitutional validation.

### Lifecycle

- A World can be read without being active.
- A proposal can be validated without being authorized.
- Authorization is a separate future contract.
- Activation is outside the first implementation slice.

## 7. RIO boundary

RIO is an interface/communication layer only in this phase.

Allowed: source/destination references, read-only World context, delivery/trace
metadata, and communication status.

Not allowed: mutating EVA state, granting authority, activating a World, or
inferring permission from delivery.

## 8. Read-only dashboard contract

The dashboard may display World identity, lifecycle state, Citadel binding,
constitutional reference, structure, regions, landmarks, provenance,
validation results, and visible unknowns/conflicts.

It must not display `APPROVED`, `ACTIVE`, or `AUTHORIZED` unless those states
are backed by their separate records and gates.

## 9. Test plan

### Unit tests

- valid EVA manifest parses;
- malformed input fails closed;
- duplicate IDs are rejected;
- missing Citadel binding returns `INCOMPLETE`;
- missing provenance returns `BLOCKED` or `INCOMPLETE`;
- unknown state remains `UNKNOWN`;
- normalization is deterministic;
- repeated input produces the same normalized digest.

### Contract and security tests

- OR6IT has no activation method in the first-slice interface;
- RIO cannot mutate World state;
- visual metadata cannot satisfy authorization;
- a validated proposal is not an authorization record;
- repository merge is not World activation;
- no credentials in fixtures or logs;
- no external network calls in synthetic tests;
- no automatic promotion from `VALIDATED` to `AUTHORIZED`.

### Acceptance test

Given `WORLD-EVA-001`:

- When OR6IT parses and validates it,
- Then it returns a deterministic read-only World proposal,
- And exposes regions, landmarks, and provenance state,
- And activates, publishes, or executes nothing,
- And leaves every missing or unknown prerequisite visible.

## 10. Implementation sequence

### Phase 0 — repository alignment

- confirm target repository and engine boundary;
- inspect current branch and package layout;
- identify canonical schema and test commands;
- do not overwrite existing contracts.

### Phase 1 — manifest contract

- add or align the World manifest schema;
- add the EVA fixture;
- add parser, normalizer, validator, and tests.

### Phase 2 — provenance and gates

- add source references and evidence-state model;
- implement read-only identity/evidence/constitutional results;
- keep authorization and activation outside scope.

### Phase 3 — read model

- expose a read-only EVA dashboard/API model;
- show validation, provenance, and unknown states;
- add browser/API tests if supported.

### Phase 4 — review and decision

- run CI and security checks;
- review schema and provenance;
- record dissent and unresolved prerequisites;
- request explicit human merge decision.

## 11. Merge gate

Do not merge if the target repository, engine boundary, schema compatibility,
or provenance is unresolved; if conflicts are silently resolved; if a
write/activation path appears; if CI/security checks fail; or if human review
has not occurred.

## 12. Decision boundary

```text
DESIGN PACKAGE
    ↓
IMPLEMENTATION REVIEW
    ↓
SCHEMA + TESTS
    ↓
PROVENANCE / CONSTITUTIONAL REVIEW
    ↓
HUMAN MERGE DECISION
    ↓
SEPARATE AUTHORIZATION DESIGN
    ↓
FUTURE ACTIVATION REVIEW
```

**Current recommendation:** prepare and review the read-only kernel only. No
activation, deployment, or external effect is included in this blueprint.
