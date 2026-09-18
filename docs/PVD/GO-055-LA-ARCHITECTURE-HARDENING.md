# GO-055 — L.A. Architecture Hardening & No-Panic Test Boundary

**Status:** IMPLEMENTED — CI verification pending

GO-055 closes the previously identified hard-rule violation in the PostgreSQL integration test suite.

## Changes

- Removed `.expect()` from `crates/palaco-la/tests/postgres_integration.rs`.
- Integration tests now return `Result<(), String>` and propagate infrastructure failures explicitly.
- Preserved assertion-based behavioral checks.
- Added an architecture test that scans the integration-test source for `.expect(` and `.unwrap(`.
- Constitutional architecture rule count: **49**.

## Boundary

The test suite must not hide infrastructure failure behind panic-oriented convenience APIs.

`ERROR → explicit Result propagation`

not

`ERROR → panic`

This applies to the L.A. integration-test boundary and does not weaken fail-closed behavior.

## Verification target

CI must establish:

1. cargo fmt
2. cargo check
3. cargo test
4. cargo clippy -D warnings
5. PostgreSQL migration
6. PostgreSQL integration suite
7. architecture boundary tests

**GREEN is not claimed until GitHub Actions reports success for the current head.**

## Next

If the complete gate passes, GO-056 should focus on evidence closure and replay-to-execution negative-path integration rather than adding another independent subsystem.
