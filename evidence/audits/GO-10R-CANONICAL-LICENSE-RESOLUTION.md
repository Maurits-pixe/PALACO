# GO-10R — Canonical License Resolution Dossier

**Repository:** `Maurits-pixe/PALACO`  
**Baseline:** PALACO Foundation Edition v1.0.0  
**Status:** AWAITING OWNER RATIFICATION  
**Publication:** FAIL-CLOSED (`publish = false`)

## Purpose

GO-10R exists solely to resolve the licensing blocker identified by GO-10 without inventing a legal or canonical decision.

## Evidence reviewed

### Current Foundation assembly

Root `Cargo.toml` currently declares:

```toml
license = "Apache-2.0"
publish = false
```

Root `LICENSE` is explicitly an assembly placeholder and states that authoritative license text must be canonically approved before release.

### Canonical implementation source

`docs/implementation/PIS/PIS-011.md` is a bounded, provenance-preserved extraction from the PALACO canonical source and includes a workspace package example declaring:

```toml
license = "MIT OR Apache-2.0"
```

Its recorded extraction source is:

- source repository: `Maurits-pixe/PALACO`
- source artifact: `PALACO CORE CANONICAL — QUAY REMEDIATION KERNEL (QUAY-006 /QUAY-007)`
- source blob: `5f9088f889cd2041d424187da80b1ed1477f396c`

### Corroborating source

`Maurits-pixe/palaco-genesis/Cargo.toml` also declares:

```toml
license = "MIT OR Apache-2.0"
```

No independent authoritative `LICENSE`, `LICENSE-MIT`, `LICENSE-APACHE`, `LICENCE`, `COPYING`, or `NOTICE` file was found in the inspected PALACO source repositories.

## Finding

The repository contains evidence for two different license declarations:

1. current Foundation assembly: `Apache-2.0`;
2. canonical/Genesis implementation sources: `MIT OR Apache-2.0`.

The evidence does not establish that the current single-license declaration was a ratified owner decision, nor does it provide the authoritative license files required to close the release boundary.

Therefore GO-10R MUST NOT silently choose or manufacture a license.

## Ratification choices

### Option A — Dual license

Ratify `MIT OR Apache-2.0`, aligning the Foundation package declaration with PIS-011 and palaco-genesis.

Closure would require:

- owner ratification of the dual-license choice;
- authoritative MIT license text with the correct copyright holder;
- authoritative Apache License 2.0 text;
- root Cargo declaration `MIT OR Apache-2.0`;
- repository license files matching that declaration;
- removal of the assembly placeholder;
- full GO-10 / GO-10R regression.

### Option B — Apache-2.0 only

Ratify `Apache-2.0`, retaining the current Foundation Cargo declaration but explicitly superseding the dual-license examples for this Foundation Edition.

Closure would require:

- owner ratification of Apache-2.0-only for Foundation Edition v1.0.0;
- authoritative Apache License 2.0 text;
- a documented canonical supersession note explaining the difference from PIS-011 / Genesis examples;
- removal of the assembly placeholder;
- full GO-10 / GO-10R regression.

## Fail-closed state

Until ratification:

- all seven Foundation crates remain `publish = false`;
- GO-10 remains technically PASS;
- release readiness remains BLOCKED;
- GO-11 Release Manifest remains LOCKED;
- no license text or copyright holder is inferred by GO-10R.

## Closure condition

GO-10R closes only after an explicit owner ratification selects a licensing model and the repository is updated and re-audited against that exact decision.
