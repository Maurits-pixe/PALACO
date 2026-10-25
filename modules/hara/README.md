# HARA development map

This directory contains isolated HARA-related candidates, not a single
integrated or production runtime. Candidate evidence is scoped to the specific
code and controls that were run; it is not production acceptance or authority.

## Proposed Citadel household layer

The proposed direction is for HARA to provide a bounded “household” service
layer for each Citadel: a local place to discover shared services, submit and
track service requests, coordinate care or maintenance, and find Citadel
information. These are design goals, not currently implemented or accepted
capabilities.

“Each Citadel” means a separately configured instance under that Citadel’s own
service catalogue, data boundary, policy, consent, and accountable operators.
It does not mean one HARA instance owns, governs, or automatically accesses
every Citadel. Cross-Citadel sharing requires an explicit contract and review.

The household function must remain distinct from both interface and
authorization:

- HARA household services do not themselves establish identity, authenticate
  residents, authorize requests, execute actions, issue ELIXERS, or govern a
  Citadel.
- A request is not permission or execution. The applicable Citadel owner or
  authorized service must make and record its own decision before any effect.
- Each service must declare its inputs, data retention, access rules, consent,
  provenance, operator, failure behavior, and revocation path before use.
- HARA, H∆R∆, HARAM, H∆R∆M, and HARA-LAB-001 / H∆R∆ remain distinct names;
  this proposal does not resolve their canonical identity or merge them.
- H∆R∆M remains a presentation-layer candidate. A Matriarch relationship to
  H∆R∆ remains `NOT_ESTABLISHED` under R3-C.

Current state: household capabilities remain
`PROPOSED / NOT_IMPLEMENTED / NOT_AUTHORIZED`. The public website includes a
separate, synthetic-only in-memory demonstration runtime at
`website/hara-runtime.js`. It exercises a fictional service-preview flow; it
does not create or submit requests, store data, contact operators, decide or
execute actions, or connect the D-012/D-013 candidates. This demonstration is
not the proposed household runtime and does not change the implementation or
authorization status above.

## Current workstreams

| Workstream | Scope | Current status | Entry point |
| --- | --- | --- | --- |
| H∆R∆ Hannie agenda, D-012 | Isolated agenda candidate with preparation, consent, policy checks, and historical recovery. Agenda execution remains denied. | Independent review pending; integration and production on hold. | [Candidate README](hannie-agenda/README.md) · [Review instructions](hannie-agenda/REVIEW.md) |
| Hannie B candidate, D-013 | Isolated SQLite transaction and crash-recovery candidate for one synthetic CREATE flow. | Specification draft; acceptance and independent review open; integration and production on hold. | [Candidate README](hannie-b-d013/README.md) · [Contract](hannie-b-d013/CONTRACT.md) |
| R3-C Matriarch review | Evidence review of the proposed H∆R∆M → Matriarch → H∆R∆ relation. | Open review; relationship not established. | [R3-C review](../../docs/ecosystem/R3-C-Matriarch-Confirmation-Review.md) |

### H∆R∆ Hannie agenda · D-012 candidate 0.3.3-d012.1

Preparation, exact approval, permission checks, and historical recovery are
available in the isolated candidate source. Agenda execution always refuses
with `STORAGE_EFFECT_DEADLINE_UNSUPPORTED`. This status overview does not
connect the candidate to the PALACO websites or a live calendar; integration
and production remain on hold.

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
