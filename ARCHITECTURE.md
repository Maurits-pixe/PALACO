# Genesis Architecture

The existing repository root is the canonical Genesis boundary. Preserve the
current workspace identity, dual license, seven foundation crates and
existing `palaco-la` extension. Do not add a competing nested workspace.

## Implemented foundation

| Crate | Current responsibility |
| --- | --- |
| `palaco-foundation` | Evidence references, authority states, validation and conservative dispositions |
| `palaco-eventbus` | Evidence-bearing event envelopes |
| `palaco-quay` | Provenance records carrying supplied authority |
| `palaco-citadel` | Mapping authority to an execution boundary |
| `palaco-runtime` | Runtime plans preserving boundary dispositions |
| `palaco-kernel` | Kernel cycles preserving runtime dispositions |
| `palaco-evolution` | Evidence-bearing proposals that always request Hold |

The existing flow carries evidence and authority from EventBus/Quay through
Citadel and Runtime to Kernel. None of these foundation types implements
constitutional amendment, real task execution or durable evidence storage.
`palaco-la` is an existing additional workspace member, not a new Genesis
subsystem introduced by this consolidation.

## Target kernel contract

```text
Constitution → Kernel(validate, authorize, execute, evidence) → Quay
Authority → Validation → Execution → Evidence → Evolution
```

This is the target boundary, not a claim that all stages are implemented.
Read the [kernel contract](docs/architecture/kernel-contract.md) for the
distinction between current APIs and future acceptance criteria.

Genesis code forbids unsafe code, denies unwrap/todo and uses no Mutex/RwLock.
Governance remains outside execution's power to redefine.
