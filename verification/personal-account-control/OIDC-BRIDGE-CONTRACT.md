# RIO OIDC refusal boundary v0.1 — candidate, not deployed

Object: reference slice v0.10 and an additive candidate change to RIO /api/me.
Production/ACCOUNT-1 remain HOLD. There is no enrollment or activation endpoint.

## Observed producer boundary

services/rio-accounts/src/lib.rs verifies the ID token through its configured
verifier and nonce, exact audience/authorized party and the two fixed synthetic
subjects before creating a server session. /api/me loads that session and reports
VERIFIED_DEV_OIDC and operativeAuthority NONE. The inspected path does not retain
or validate a strong-authentication/MFA attestation. Identity verification is
therefore insufficient for the personal-account activation gate.

The candidate adds personalAccountControl to the authenticated /api/me response:

```json
{
  "schema": "rio-personal-account-boundary/v1",
  "strongAuthentication": "UNKNOWN",
  "lifecycleAuthority": "NONE",
  "activationEligible": false,
  "reason": "STRONG_AUTHENTICATION_EVIDENCE_MISSING"
}
```

lifecycle_bridge.rs produces this fixed refusal metadata without accepting any
client claims. Existing mode/account1/accountActive/authority values stay as
before. No email, token, assurance claim, role or actor is added by the boundary.
The response change is source code only: the service has not been compiled,
started or deployed with it in this task.

## Consumer boundary

oidc_bridge.assess classifies a candidate synthetic /api/me-shaped object. It
always returns BLOCKED, activationEligible false and authority NONE. A supported
boundary explains missing evidence; malformed, promoted or unsupported metadata
reports UNSUPPORTED_OR_INVALID_METADATA. The classifier does not issue a session,
validate an ID token, trust arbitrary JSON as identity or accept client amr/acr
hints as stronger proof. CSRF/session values and actor IDs are not echoed.

This refusal-only bridge is intentionally not connected to FixtureSessions.seed:
a synthetic strong=True flag must never be derived from VERIFIED_DEV_OIDC alone.
A future admission path needs real authentication-strength policy and verified
server-side evidence plus the existing review/mandate/lifecycle gates.

## Executed and blocked checks

- Six Python refusal-contract tests execute locally, together with all existing
  slice tests and the eight existing review-gate tests.
- The dependency-free Rust lifecycle_bridge module compiles and passes its one
  unit test with rustc --test; this checks only that standalone boundary module.
- rustfmt --check accepts the candidate Rust source.
- Full cargo test --locked --manifest-path services/rio-accounts/Cargo.toml --lib
  was attempted but blocked: axum is absent from the offline cache and the
  crates.io index is unreachable through the configured proxy. No full-service
  compilation, router assertion execution or live OIDC test PASS is claimed.

The existing /api/me regression test was extended to assert the exact boundary,
but remains NOT EXECUTED until full-service dependencies are available. No lockfile
or dependency version was changed to work around this failure.

## Review and next transition

AI review: TRIAS — login cannot silently supply activation authority; all HOLD
gates retained. ORACLE — isolated Rust and Python refusal tests are distinct from
unexecuted full-service checks. MENTOR — rerun the full existing Rust library/router
suite once dependencies are reachable before treating this candidate response as
implemented runtime behavior. Real MFA policy/attestation and authorized activation
remain separate unresolved gates. No user approval is inferred from this module.
