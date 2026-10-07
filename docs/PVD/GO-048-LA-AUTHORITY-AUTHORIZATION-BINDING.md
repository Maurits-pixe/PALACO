# ∆ GO-048 — L.A. AUTHORITY ↔ AUTHORIZATION IDENTITY BINDING

## Constitutional rule

An Authorization SHALL reference the exact Authority under which it was issued.

```
AUTHORITY
  ↓
AUTHORIZATION.authority_id
  ↓
EXECUTION PERMIT
  ↓
EXECUTION
```

A lifecycle evaluation MUST reject a mismatched Authority before execution may continue.

## COMET relationship

```
REVOKE AUTHORITY
  ↓
AUTHORITY STATUS
  ↓
COMET PROPAGATION
  ↓
AUTHORIZATION BINDING
  ↓
EXECUTION LIFECYCLE
  ↓
STOP / REASSESS
```

## Hard boundaries

- AUTHORITY != AUTHORIZATION
- AUTHORIZATION MUST REFERENCE AUTHORITY
- MISMATCHED AUTHORITY => STOP
- REVOCATION DOES NOT REWRITE HISTORY
- SIGNATURE != AUTHORITY
- PROVENANCE != PERMISSION

## Non-goals

This change does not create authority from a Decision, signature, provenance record, intelligence output or RIO interaction. It also does not authorize execution merely because an Authority is cryptographically valid.

## Verification

GO-048 adds explicit typed Authority identity to Authorization and a lifecycle mismatch test. GitHub Actions remains the final compile/test/Clippy gate.