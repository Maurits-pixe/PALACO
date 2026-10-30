# GO-10 PostgreSQL Audit Repair

**Status:** Implementation candidate  
**Triggering failure:** GO-10 run `41020107550`  
**Failure point:** `cargo test --workspace --all-targets`

## Root cause

The workspace now includes `palaco-la` PostgreSQL integration tests.

Those tests correctly fail when `DATABASE_URL` is absent. GO-10 executed the
entire workspace test suite without provisioning the PostgreSQL service that
the L.A. integration contract requires.

Observed failure:

```text
DATABASE_URL must be supplied by the PostgreSQL CI service: NotPresent
```

Five PostgreSQL integration tests failed for that single infrastructure reason.

## Remediation

GO-10 now:

1. provisions PostgreSQL 17;
2. configures the same database/user contract as the existing PALACO L.A. gate;
3. exports `DATABASE_URL=postgres://postgres:postgres@localhost:5432/palaco`;
4. explicitly verifies PostgreSQL readiness before Rust tests;
5. runs on pull requests to `main` as well as pushes to `main`.

## Safety rule

The PostgreSQL tests remain mandatory. They are not ignored, conditionally
skipped, or removed from `cargo test --workspace --all-targets`.

## Acceptance

The repair closes only when a pull-request GO-10 run demonstrates:

- PostgreSQL readiness PASS;
- workspace tests PASS, including all five `palaco-la` PostgreSQL tests;
- explicit PVS-002 integration PASS;
- GO-09 Evidence Seal verification PASS;
- GO-10 machine audit PASS.
