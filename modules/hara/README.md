# HARA development map

This directory contains isolated HARA-related candidates, not a single
integrated runtime. Candidate evidence is scoped to the specific code and
controls that were run; it is not production acceptance or authority.

## Current workstreams

| Workstream | Scope | Current status | Entry point |
| --- | --- | --- | --- |
| H∆R∆ Hannie agenda, D-012 | Isolated agenda candidate with preparation, consent, policy checks, and historical recovery. Agenda execution remains denied. | Independent review pending; integration and production on hold. | [Candidate README](hannie-agenda/README.md) · [Review instructions](hannie-agenda/REVIEW.md) |
| Hannie B candidate, D-013 | Isolated SQLite transaction and crash-recovery candidate for one synthetic CREATE flow. | Specification draft; acceptance and independent review open; integration and production on hold. | [Candidate README](hannie-b-d013/README.md) · [Contract](hannie-b-d013/CONTRACT.md) |
| R3-C Matriarch review | Evidence review of the proposed H∆R∆M → Matriarch → H∆R∆ relation. | Open review; relationship not established. | [R3-C review](../../docs/ecosystem/R3-C-Matriarch-Confirmation-Review.md) |

These workstreams are separate. In particular, the D-012 agenda candidate and
D-013 transaction candidate do not together constitute an integrated HARA
system, and evidence from one is not evidence for the other.

## Boundaries

- A candidate label, role listing, or package name does not establish canonical
  identity, family membership, or authority.
- H∆R∆M's appearance in a role list or as a Citadel space does not establish
  that it is the Matriarch of H∆R∆. The R3-C relationship remains
  `NOT_ESTABLISHED`.
- No identity merge, authority inheritance, capability inheritance, namespace
  inheritance, issuer status, or signer status is inferred between HARA,
  H∆R∆, H∆R∆M, HANNIE, or other named entities.
- Local test success is scoped to the tested candidate. It does not establish
  live identity, production readiness, official proof, integration, or
  deployment.

## Candidate checks

Requirements are listed in each candidate README. With the documented Node
version and platform dependencies installed, run a candidate's local tests
from its own directory:

```sh
cd modules/hara/hannie-agenda
npm test
```

```sh
cd modules/hara/hannie-b-d013
npm test
```

The `verify` scripts create fresh evidence runs; use them only when intentionally
producing new candidate evidence. They do not replace independent review or
authorize integration, production, merge, or deployment.

## Next gates

Each candidate requires its own exact source revision, reproducible evidence,
and independent review. Any integration proposal must separately bind identity,
authorization, policy, runtime, and operational boundaries, then receive the
applicable human decision. Until those gates are met, the stated HOLD statuses
remain in force.
