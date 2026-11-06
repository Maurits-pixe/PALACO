# HARA service preparation — candidate v0.1

Pure local preparation for the requested PALACO ONE route. `prepareServiceTask`
returns a deeply frozen, digest-bound draft; it performs no network, filesystem,
authentication, clock validation, approval issuance or dispatch. No PALACO ONE
host is connected. This is not an operational service employee.

Consumer input is exactly `{purpose:'CONSUMER',context,request,deadlines}`.
Context and request are **unverified caller data**. The existing Hannie candidate's
`prepareConsent` supplies its exact request/profile validation and late-completion
disclosure. This module records no consent selection. Even an expired deadline
can be prepared: only the genuine host may validate current time and authority.

Maintenance input is exactly
`{purpose:'MAINTENANCE',repository,sourceCommit,changeSummary,verificationPlan}`.
The repository is an `owner/name` reference and sourceCommit is a full lowercase
40-character Git SHA. These are supplied references, not verified source existence
or ownership. Verification steps are plain text, never shell commands to run.
No consumer context or execution credential is accepted by this branch.

Both return `DRAFT_REQUIRES_HOST_VERIFICATION`, `authorityGranted:false`,
`canExecute:false` and `hostBinding:'UNRESOLVED'`. The digest is SHA-256 over the
JSON encoding of recursively sorted object keys in the versioned binding
`{contract,requestedRoute,purpose,proposal}`; arrays retain order. It covers the
proposal, not provenance, authorization, storage or a server-issued identity.
The fixed explanatory/status fields are outside that proposal digest. A caller
can forge a draft or digest; no verifier may treat one as permission.

Only ordinary bounded JSON data is supported. The output is detached from input
and recursively frozen. Accessors and exotic objects are rejected, but callers
are still local code: this library is not an isolation boundary against hostile
JavaScript/Proxy execution. Present strings as text, never trusted HTML.

Run `npm test` here (Node >=24.14.1). Tests are separate from the existing
75-control runtime evidence. The module imports the candidate's pure client/value
modules; it does not import its runtime or fixture issuer. The original D-013 and
validation-deadline implementations are unchanged.

Next: identify the real PALACO ONE host, bind principal/origin/grant/time/approval
interfaces, then implement and verify the real boundary before any dispatch.
See `evidence/hara/validation-deadline/PALACO-ONE-SERVICE-CONTRACT-2026-11-05.md`.
