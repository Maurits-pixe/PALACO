# PALACO.NL — PVD-001 v1.0

**Status:** GO-6 implementation baseline · DRAFT  
**Branch:** `go-6/palaco-nl-v1`  
**Reference Citadel:** L.A. / Locus Amoenus (`LA-001`)

PALACO.NL is the public gateway into the PALACO constitutional architecture. Its public loop is **arrive → understand → explore → participate → verify → identify → return**.

## Implemented slice

- quiet PALACO threshold with `ENTER PALACO`;
- primary navigation for Citadels, Elixirs, Proof, Industrie, Governance and Evolution;
- L.A. reference Citadel with Perimeter → Crown → Four Towers → Core journey;
- Proof / verification surface with explicit `UNVERIFIED` result when no provider is connected;
- provenance chain, Watermerk, Identity, H∆R∆M, Stewardship, About and Constitution routes;
- responsive, keyboard-navigable static shell with reduced-motion support;
- structured seed data under `website/data/`.

## Constitutional boundary

The frontend presents records and navigation. It does not issue identity, create authority, infer trust, or claim verification from a PALACO mark. A live Proof provider, issuer, Seal chain and revocation source must be connected and separately verified before a future release can return `VERIFIED`.

## Route model

`/`, `/citadels`, `/citadels/la-001`, `/elixirs`, `/proof`, `/proof/verify`, `/proof/provenance`, `/proof/watermerk`, `/identity`, `/industrie`, `/governance`, `/evolution`, `/haram`, `/stewardship`, `/about`, `/constitution`.

The first static implementation uses hash navigation (`#/...`) so a direct link does not depend on server-side rewrites. The conceptual public paths remain the canonical information architecture.

## Release pipeline

`CONCEPT → CONTENT → DESIGN → PROVENANCE → ACCESSIBILITY → SECURITY → PROTOTYPE → REVIEW → VERSION → RELEASE`.

This commit closes the prototype baseline only. Publication and claims of live verification remain later gates.
