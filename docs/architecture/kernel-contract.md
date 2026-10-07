# Kernel Contract

## Target boundary

```text
Constitution
    ↓
Kernel
    ├── validate
    ├── authorize
    ├── execute
    └── evidence
            ↓
           Quay
```

Execution is allowed only after validation and authorization. Every completed
action must produce attributable evidence. Governance may constrain execution;
execution may never silently redefine governance.

## Existing APIs, not a completed engine

[`KernelCycle`](../../crates/palaco-kernel/src/lib.rs) consumes a
[`RuntimePlan`](../../crates/palaco-runtime/src/lib.rs), preserves its
disposition, exposes `can_execute` and delegates `Validatable::validate`.
It does not execute actions or emit completion evidence.
The current [`Quay`](../../crates/palaco-quay/src/lib.rs) carries input
provenance; it is not a durable completion-evidence sink.

`Authorized` maps to Execute, revoked/expired authority maps to Deny and
indeterminate authority maps to Hold. `can_execute` reports the disposition;
it is not a standalone authorization service. Evolution proposals request
Hold and do not grant authority.

The existing
[cross-crate tests](../../crates/palaco-kernel/tests/pvs002_cross_crate.rs)
check these boundaries. Future A1.3/A1.4 work must supply evidence for real
execution and completion evidence without silently claiming those features
already exist.
