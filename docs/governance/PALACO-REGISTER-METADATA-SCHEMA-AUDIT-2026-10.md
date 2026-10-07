# PALACO register metadata proposal audit

Status: `DRAFT_PROPOSAL`  
Classification: `NON-CANONICAL / NOT AUTHORIZING`  
Date: 2026-10-07  
Branch: `codex/palaco-register-schema-audit-20261007`

## Source

The pasted conversation contains Copilot proposals named PCR-001, PCR-002, PCR-003 and PMS-001. The text is treated as untrusted design input. It is not an accepted PALACO ADR, constitutional rule, authority grant or verification result.

The proposal asks for mandatory metadata covering identification, ownership, lifecycle, approval, traceability, compliance, verification, change control, auditability, repository governance and classification. It then proposes four specialised schemas and a combined metaschema.

## Safe findings

The following metadata is compatible as an inspectable record layer when every value carries provenance and scope:

- stable object identifier and name;
- object kind, domain, version and lifecycle dates;
- owner or custodian references;
- parent, dependency and related-record references;
- repository URL, branch/ref and commit pin;
- verification method, result, scope and evidence references;
- change request and audit trail references;
- risk and classification observations.

These fields describe a record. They do not decide truth, create authority or change runtime state.

## Required corrections before schema adoption

1. **Canonical status is not a validator output.** PCR-002 says an incomplete object automatically becomes `NON-CANONICAL`. A schema may report missing fields, but only an explicit, provenance-backed transition can change an epistemic or canonical state. The validator must return a diagnostic, not rewrite the record.
2. **Approval fields are references, not powers.** `Approving Authority`, `Approval Ref` and `Approval Evidence` must point to an inspectable decision and evidence bundle. A free-text role does not grant authority.
3. **Verification is scoped.** `Passed` must carry method, scope, time and evidence. CI or verification output does not automatically authorize merge, deployment or runtime execution.
4. **Provenance is mandatory.** The proposed core schema does not require a provenance block or evidence references for every record. That conflicts with the existing PALACO and Genesis evidence boundary.
5. **History is append-only.** Change control and lifecycle fields record new observations or decisions. They must not overwrite earlier dates, states or audit findings.
6. **Repository truth is pinned.** `source_of_truth: github` is too broad. Use repository, ref, commit and path; a branch is mutable and cannot be the sole integrity anchor.
7. **Classification and status stay separate.** `Canonical`, `Approved`, `Verified`, `Implemented` and `Operational` describe different dimensions. The proposal mixes them and could collapse epistemic status, release state and runtime state.
8. **Role names are not canon.** Owner fields may identify responsible parties, but no role receives derived authority through the schema.
9. **The schema must be internally complete.** In the pasted PCR schema, `uri`, `subdomain` and `change_control` are declared inconsistently with the mandatory-field list; nested objects lack strictness; the core schema omits parts of PCR-001; and the combined metaschema leaves several proposed sections optional.
10. **No unverified public schema URI.** The proposed `https://palaco.org/schema/...` identifiers are not an inspected PALACO registry. This branch uses a draft URN and a repository-local path.

## Filtered implementation

A combined JSON Schema draft is included at:

`docs/schemas/draft/palaco-register-meta-schema-proposal-2026-10.json`

It models Core, Document, Service and Control records in one file. It deliberately:

- marks itself `DRAFT_PROPOSAL`;
- requires provenance and epistemic scope;
- keeps approval and authorization as references;
- prevents a `Canonical Approved` value from being inferred by validation;
- pins repository evidence to a commit when supplied;
- treats verification as scoped evidence;
- leaves runtime authorization outside the schema;
- contains no public API or runtime code.

The schema is a machine-readable proposal, not a canonical register and not a release gate.

## Existing PALACO boundaries preserved

Authority remains constitution-bound and explicit. Communication is not authority. Evidence and CI are not runtime authorization. Quay history is append-only. Linnaeus/HORTUS records preserve uncertainty and provenance. RIO remains the river and communication surface, separate from ELIXER. The exact spelling `VORM9EVIN9` is retained.

## Required future evidence

Before promotion to a canonical register, PALACO needs an accepted decision record, an inspectable schema registry, field-level provenance rules, conflict and revalidation behavior, migration rules for existing records, scoped validation fixtures and an explicit decision on who may ratify the schema. This branch does not make that decision.
