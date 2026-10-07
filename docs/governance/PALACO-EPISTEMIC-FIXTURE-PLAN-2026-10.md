# PALACO epistemic fixture plan

**Status:** DRAFT fixtures / not executed / non-canonical  
**Date:** 2026-10-07

This fixture pack turns the candidate ETCG, KESG, KAG, Linnaeus/HORTUS, source-independence, conflict and authority boundaries into reviewable negative cases. The JSON manifest is test input, not test evidence. No fixture claims a PASS, certification, constitutional ratification or runtime authorization.

## Execution rule

A future runner may evaluate each fixture only in a declared environment and record:

- exact input and checked-out revision;
- evaluator and method;
- observed result;
- expected result;
- evidence/provenance references;
- timestamp and temporal context;
- failure or indeterminate reason.

A fixture result cannot create authority. It must remain scoped to the contract it tests.

## Fixture coverage

The manifest covers direct state overwrite, missing provenance, stale evidence, copied-source chains, unsupported opinions, identity conflict, conflict replay, KESG/KAG separation, adequacy without authorization, CI/evidence without runtime permission, RIO/ELIXER separation and VORM9EVIN9 status fidelity.

Expected outcomes such as REJECT, INSUFFICIENT, IN_DOUBT, BLOCKED and NO_AUTHORIZATION are safe-stop outcomes. They are not claims that the implementation already produces them.

## Required evidence before execution

Before running these fixtures, the repository must provide a versioned contract, deterministic evaluator, fixture loader, append-only result record and Quay reconstruction path. The runner must not mutate canonical state or use a passing result as permission to merge, deploy or execute.

See the [draft specification](https://github.com/Maurits-pixe/PALACO/blob/codex/palaco-epistemic-fixtures-20261007/docs/governance/PALACO-EPISTEMIC-DRAFT-SPEC-2026-10.md) and [JSON manifest](https://github.com/Maurits-pixe/PALACO/blob/codex/palaco-epistemic-fixtures-20261007/docs/fixtures/epistemic/next-go-fixtures.json).

Exact spelling required in surface-semantic fixtures: VORM9EVIN9.
