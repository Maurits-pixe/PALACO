# GO-10R — Canonical License Ratification

**Repository:** `Maurits-pixe/PALACO`  
**Baseline:** PALACO Foundation Edition v1.0.0  
**Ratification date:** 2026-09-28  
**Decision:** Option A — `MIT OR Apache-2.0`  
**Status:** RATIFIED

## Decision

The owner selected **Option A** from the GO-10R license resolution dossier.

The PALACO Foundation Edition v1.0.0 licensing model is therefore canonically ratified as:

```text
MIT OR Apache-2.0
```

A recipient may use the Foundation under either the MIT License or the Apache License, Version 2.0, at their option.

## Repository implementation

The ratification is implemented by:

- root Cargo expression: `license = "MIT OR Apache-2.0"`;
- root `LICENSE` dual-license declaration;
- `LICENSE-MIT` containing the MIT License;
- `LICENSE-APACHE` containing the Apache License, Version 2.0;
- all seven Foundation crates inheriting the workspace license expression;
- `publish = false` remaining enabled as a separate release/distribution safety gate.

## Canonical reconciliation

This decision aligns the Foundation Edition with the explicit `MIT OR Apache-2.0` declaration already present in PIS-011 and in the PALACO Genesis workspace.

The previous Foundation-only `Apache-2.0` declaration is superseded by this ratification for Foundation Edition v1.0.0.

## Historical evidence

GO-09 remains unchanged. Its statement that licensing was unresolved describes the historical sealed subject at that time and is not retroactively rewritten.

## Closure rule

GO-10R is CLOSED only when:

1. Cargo metadata matches the ratified expression;
2. all license files are present and non-placeholder;
3. all seven crates inherit the workspace expression;
4. the GO-10R machine verifier passes;
5. the full GO-10 audit passes with no licensing release blocker.

