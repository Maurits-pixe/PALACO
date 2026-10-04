# GO-10R — Canonical License Resolution Dossier

**Repository:** `Maurits-pixe/PALACO`  
**Baseline:** PALACO Foundation Edition v1.0.0  
**Status:** RATIFIED / IMPLEMENTED / PENDING FINAL REGRESSION  
**Decision:** Option A — `MIT OR Apache-2.0`  
**Publication:** FAIL-CLOSED (`publish = false`)

## Resolution

The owner selected **Option A**.

The Foundation Edition v1.0.0 canonical license expression is:

```toml
license = "MIT OR Apache-2.0"
```

This aligns the Foundation with the explicit dual-license declaration already present in PIS-011 and in the PALACO Genesis workspace.

## Implemented artifacts

- `Cargo.toml` → `license = "MIT OR Apache-2.0"`
- `LICENSE` → dual-license choice declaration
- `LICENSE-MIT` → MIT License
- `LICENSE-APACHE` → Apache License, Version 2.0
- `evidence/audits/GO-10R-LICENSE-RATIFICATION.md` → owner ratification record
- all seven Foundation crates inherit workspace license metadata
- `publish = false` remains enabled

## Historical reconciliation

Before ratification, the repository contained:

1. a current Foundation assembly declaration of `Apache-2.0`;
2. canonical/Genesis implementation evidence for `MIT OR Apache-2.0`.

The ratification resolves this ambiguity in favor of the dual-license model. The earlier single-license Foundation declaration is superseded for Foundation Edition v1.0.0.

GO-09 remains unchanged as historical evidence of the state before the licensing decision.

## Closure condition

GO-10R closes when both conditions hold:

1. GO-10R License Resolution Guard reports the ratified dual-license state as PASS;
2. GO-10 Foundation Audit reports `release_blockers=NONE`.

Until those regressions are green, GO-11 remains locked.
