# HARA authority and time source binding — 2026-11-05

Status: SOURCE COMPARISON COMPLETE / OPERATIONAL BINDING UNRESOLVED / INTEGRATION AND PRODUCTION HOLD.

This document advances the next transition after the bounded synthetic storage review. It does not select an identity provider, grant authority, establish trusted time, or change the adopted synthetic deadline profile. The executable candidate remains at 09878183a623b3188a4fec962348c0c06d0ebd1f. The accompanying JSON records explicit null provider selections rather than invented endpoints.

## Existing authentication sources

| Source | Established evidence | Remaining HARA gap |
| --- | --- | --- |
| [BOOK-1 merged snapshot](https://github.com/Maurits-pixe/PALACO-BOOK-1/tree/393b0596ec4b1bb87d73d3e9ec81e08e00133031) | identity.ts resolves hashed opaque sessions against active users, expiry and revocation; actor.ts supports session or configured trusted-proxy mode; authorization.ts checks application roles/actions. | No established HARA tenant, calendar ownership, grant generation, exact approval issuer or federation mapping. OWNER is an application role. actor.ts does not return the session binding that identity.ts exposes. |
| [INDUSTRIE merged snapshot](https://github.com/Maurits-pixe/PALACO-INDUSTRIE/tree/d462e02de35dd9cea54c50fb6180bfd07c76aa30) | Root server.js implements a separate SQLite account/session store, hashed opaque tokens, CSRF and session cookies. | No established HARA issuer or cross-application session/tenant binding. Shared cookie names are not federation. |
| [RIO source review](identity-source-review.json) | Exact previously checked source is explicitly loopback synthetic OIDC/sessions for fictitious test actors. | Cannot supply genuine HARA authority. |
| Local kernel/runtime and release-registry adapters | Contract/disposition wrappers and verified-input interval logic exist. | In-memory Authorized states and caller-supplied verified flags are not credential or temporal evidence services. Local checkout is historical; this observation is bounded to examined files. |

All four source files in the JSON were fetched at immutable merged commits. BOOK-1's three observed default-branch blobs also matched these snapshot blobs. These are implementation snapshots, not proof of the current default-branch tip, deployment, configuration or account ownership.

The [authentication audit](https://www.notion.so/73382335c8a0493f8e899d8090ce466c) is historical. Its unmerged remediation status is superseded: [INDUSTRIE PR 30](https://github.com/Maurits-pixe/PALACO-INDUSTRIE/pull/30) and [BOOK-1 PR 5](https://github.com/Maurits-pixe/PALACO-BOOK-1/pull/5) were confirmed merged on 2026-09-26. Neither PR establishes shared HARA identity. Repository access and merged fixes do not establish a live authority service.

## Normative source constraints

- [Identity & Authority Conformance Harness](https://www.notion.so/e73c6a8396ec49eda7dacc11cf521355): distinguish VALID, EXPIRED, REVOKED, UNKNOWN and OUTOFSCOPE; missing identity/provenance/authorization links fail closed. This is a specified conformance contract, not operational proof.
- [Priority 1 Adapter Contract](https://www.notion.so/d7181eab708e47bc8a858196f2304f0d): preserve immutable expected/actual values and public boundaries; adapters cannot supply hidden authority. No callable production service was established.
- [ERA-017 recovery](https://www.notion.so/3e129e9a126a80aab0f5f109c6679379): key possession, identity, provenance and authority remain distinct; recovery cannot create its own historical trust anchor.
- [ERA-005 Traceable Time Source Infrastructure](https://www.notion.so/3e029e9a126a8024becac12ae9667f0d): time observations require provenance, uncertainty, freshness and evidence; recording a time value does not make it authoritative. Conceptual API descriptions do not establish a deployed endpoint.
- [ERA-012 temporal consistency](https://www.notion.so/3e129e9a126a80e7a191f71f975d4a8c): physical time, causal order and commit order remain distinct. Uncertainty cannot be removed by local sorting.
- [Historical execution report](https://www.notion.so/6ef8835019b94fee9b9ac35819e448b3): its earlier environment/toolchain block does not describe the current workspace.

The ERA catalogue uses different labels for ERA-005 in different documents. References here bind to the exact linked page/title; no canon reconciliation is inferred. Notion pages are mutable observations, not signed or immutable canon snapshots.

## Concrete integration prerequisites

Before implementing a genuine adapter, bind the identity deployment and accepted issuer/trust anchor; owner/tenant/calendar mapping; session identifier, expiry, revocation and trust epoch; authenticated origin; and the exact challenge/consent approval issuer. The issuer must atomically consume the challenge and issue an approval tied to the selected profile, request and current grant generation. Dispatch and content read must revalidate their respective current authority.

For time, bind the temporal evidence deployment, accepted signer/source provenance, evidence schema and verifier, uncertainty interval, freshness, restore continuity and rollback policy. The complete accepted interval must prove validation strictly before both expiries; overlap or missing evidence cannot satisfy that check. A local Date value, an assertion named verified, or ordinary network time alone does not establish this binding. Exact durability time remains UNKNOWN under the adopted profile.

The user directed: “SERVICE MEDEWERKER VOOR CONSUMER EN ONDERHOUD AAN HET PALACO PROGRAMMA. GEBRUIK PALACO ONE IN DE UITVOERING, GO”. PALACO ONE is therefore the requested execution route; its operational service/issuer/time binding remains unresolved. Bounded repository-name, code and Notion searches did not establish a uniquely identified PALACO ONE implementation. This finding is not proof of absence. Do not silently substitute INDUSTRIE or BOOK-1.

### PALACO ONE service employee: implementation boundary

Treat consumer assistance and PALACO maintenance as separate task purposes. A task must bind the consumer owner, tenant, target resource, requested action, exact input digest, selected deadline profile, consent/approval reference, current grant generation and time evidence. Consumer access does not imply program-maintenance access. Maintenance execution additionally needs a separately authorized target and action scope; a service employee role is not an unrestricted administrator.

The first concrete adapter must resolve PALACO ONE's authenticated subject/session and origin, then obtain authoritative ownership, grants and time evidence. Missing bindings yield HOLD before challenge issuance, dispatch or content release. No browser header, persona vote or service-role label can populate these trusted values. Inspection and proposals can proceed within existing access; program changes, updates, quarantine or deletion require the appropriate concrete mandate and verification.

The [HARA core-team contract](https://www.notion.so/13d0fa12fa084e619a6a8abde456df8f) supports consumer service and authorized maintenance, with no shared unlimited service account. The [servicewrapper/recovery contract](https://www.notion.so/3ee29e9a126a8160b6a2f99ff18a75d1) requires host-bound subject/tenant/session and trusted time; it does not itself supply that host. These are functional constraints, not operational PALACO ONE evidence. No provider is silently selected and no fake production endpoint is added.

## Review and evidence boundary

Own AI review with three lenses: TRIAS preserves existing scope and separates account identity from HARA authority; ORACLE binds code observations to commits/blobs and separates mutable specifications from deployment evidence; MENTOR identifies the smallest missing operational references instead of adding another synthetic authority flag. This is not independent acceptance.

No runtime code changed in this step. The 75 controls per Node version from [CI 41977701714](https://github.com/Maurits-pixe/PALACO/actions/runs/41977701714) remain evidence for implementation head 09878183a623b3188a4fec962348c0c06d0ebd1f, not for genuine authentication or time. Documentation/JSON consistency is checked separately. No credentials inspected, service contacted for authentication, deployment changed, merge performed or proof issued.

Coverage: bounded connected GitHub/Notion research plus identified local files. The broad connector search tool was unavailable. Absence of a binding in these sources is not proof that no suitable service exists.
