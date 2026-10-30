# GO-14 — Release Lineage Continuity

**Status:** Implementation candidate  
**Baseline release:** PALACO Foundation Edition v1.0.0  
**Release tag:** `v1.0.0`  
**Release commit:** `5283a560dc9d410fa778d69f93bb339dbafbf5fe`

## Purpose

GO-14 protects continuity between the immutable Foundation v1.0.0 release and
subsequent development. It does not change, reopen, or reinterpret v1.0.0.

## Required invariants

1. `v1.0.0` remains the same annotated tag object.
2. The tag continues to target the exact Foundation release commit.
3. Every candidate for `main` remains descended from that release commit.
4. `main` remains governed by an active strict ruleset requiring
   `standards-conformance`.
5. That ruleset has no bypass actors.
6. GO-13 continues to define the required `standards-conformance` job.
7. GO-12I server-side tag prevention remains a separately visible condition;
   its absence must never be misreported as enforced protection.

## Non-claims

GO-14 does not claim that newer `main` commits are part of Foundation v1.0.0.
It does not mutate the release tag, publish packages, deploy software, or grant
constitutional authority.

The immutable release identity remains:

`v1.0.0 → 5283a560dc9d410fa778d69f93bb339dbafbf5fe`
