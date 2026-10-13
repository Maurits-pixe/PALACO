# T04 — Independent human acceptance gate (RIO synthetic mobile)

### Status
GATE PREPARED / HUMAN REVIEW PENDING / SYNTHETIC_ONLY.
Automated T04 engineering checks: PASS on the frozen code below.
Independent security, privacy, operations, manual accessibility and physical-device evidence: NOT ACCEPTED.
ACCOUNT-1, personal enrollment, real invitations, NOVA, integration, production and merge: HOLD.

### Last Updated
2026-10-14

## Frozen automated engineering envelope

| Item | Evidence |
| --- | --- |
| Repository / PR | `Maurits-pixe/PALACO` / [PR #49](https://github.com/Maurits-pixe/PALACO/pull/49), OPEN / DRAFT / UNMERGED at gate preparation |
| Candidate branch | `feature/rio-accounts-synthetic-dev` |
| Frozen tested head | `25a0091674dbbe60e469ad025c9c2c2e2fd8e3e7` |
| Recorded base branch/SHA | `main` / `deb9f80e8c40c03f08021b044a9c31a03c4935ec` |
| [RIO run](https://github.com/Maurits-pixe/PALACO/actions/runs/38474930196) | PASS: 7/7 mobile browser (5 Android-emulation + 2 desktop keyboard), 5/5 Keycloak OIDC browser, 4/4 durable browser phases; PostgreSQL consent/storage, backup/restore, Rust/build/Clippy/docs, fixture cleanup |
| [GO-13 run](https://github.com/Maurits-pixe/PALACO/actions/runs/38474930189) | PASS |
| [PALACO L.A. run](https://github.com/Maurits-pixe/PALACO/actions/runs/38474930180) | PASS |
| Product boundary | local Keycloak + Rust/axum BFF + PostgreSQL, two fictional actors TST-alpha and TST-beta; same-origin HTTPS; no real account |

The frozen head above proves the automated test scope, not independent acceptance. A new head, changed base, changed provider configuration, changed test workflow or materially modified frontend requires a new evidence envelope and impact assessment. A hash establishes version identity, not correctness.

## Manual-accessibility and real-device gate

The existing `https://localhost:8088` BFF and its `127.0.0.1` test issuer are LOOPBACK ONLY on the developer host; opening that URL on a phone does **not** reach the fixture. [The existing verification README](../../verification/rio-accounts/README.md) already describes the distinct physical two-phone preparation. Neither its transport proof nor its required trusted private-LAN/TLS arrangement is implemented or authorized by this gate. **Do not expose the loopback fixture, bypass TLS warnings, rewrite the issuer, create hosting, install device trust roots or provision services merely to obtain a PASS.** Until an authorized, reviewed *synthetic-only* physical-device access path exists, mark physical-device cases `BLOCKED`, not `PASS`. Desktop manual keyboard/screen-reader testing may be performed separately against an already prepared local fixture, if safely accessible.

Use `NOT_RUN | BLOCKED | FAIL | PASS` for every scenario; never infer PASS from Playwright emulation. Any unexpected account/contact privilege or cross-actor data exposure is an immediate `FAIL / SECURITY BLOCKER`.

| Case | Human execution and acceptance criterion | Initial state |
| --- | --- | --- |
| H04-A01 | On an authorized physical Android device, identify Android/browser versions (no device serial); traverse login, Account, Toestemming and Studio via TalkBack; every label, role, state and status message is announced intelligibly, and visual text matches spoken meaning | BLOCKED — trusted physical access path absent |
| H04-A02 | On the physical device, navigate using touch and external keyboard: predictable focus order, no trap, visible focus, reachable revoke/logout/import/export, no hidden protected action after logout | BLOCKED — trusted physical access path absent |
| H04-A03 | Reflow at 320 CSS px equivalent, portrait/landscape, 200% text/zoom and increased text spacing: no clipped text, horizontal two-dimensional scrolling for normal content, overlapping buttons or concealed error guidance | BLOCKED — trusted physical access path absent |
| H04-A04 | Using TalkBack, confirm unselected test-consent checkbox: reading/importing does not grant consent; explicit grant announces receipt; revoke announces change; revision conflict and expired/revoked/outage responses are understandable, with a fresh deliberate choice required | BLOCKED — trusted physical access path absent |
| H04-A05 | Local Studio: safely load a benign concept and reject a fake role/consent/credential JSON; note stays local; no server account mutation; imported data never becomes a trusted identity | BLOCKED — trusted physical access path absent |
| H04-A06 | On a desktop with keyboard and a screen reader actually running, perform the same focus/status/consent/revoke/logout checks against the isolated local fixture; record screen reader/browser versions and failures | NOT_RUN — human operator needed |
| H04-A07 | Independently inspect WCAG 2.2 AA-relevant criteria: 1.4.10 Reflow, 2.1.1 Keyboard, 2.1.2 No Keyboard Trap, 2.4.3 Focus Order, 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured, 3.3.8 Accessible Authentication (Minimum), 4.1.2 Name/Role/Value, 4.1.3 Status Messages; log applicability and findings rather than asserting whole-site WCAG conformance | NOT_RUN — human accessibility reviewer needed |

References: [W3C WCAG 2.2 Understanding](https://www.w3.org/WAI/WCAG22/Understanding/), [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html), [focus visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible), [status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html).

## Independent review gates (separate human reviewers, not AI self-approval)

| Gate | Human questions / required evidence | Initial state |
| --- | --- | --- |
| H04-SEC | Review frozen code + BFF/Keycloak/PostgreSQL config: exact issuer/audience/redirect, nonce/PKCE, session cookie flags, host/origin/CSRF, tenant/actor binding, consent CAS/revoke, session rotation, error/timeout fail-closed, clock rollback, revocation persistence and recovery fencing. Inspect negative cases and dependency/security scan findings; note unresolved audit-quota saturation test. | NOT_RUN |
| H04-PRIV | Confirm purposes, local concept handling, absent telemetry/credential export, synthetic fixtures only, retention/deletion and backup exceptions, masking/logging, consent semantics, and unresolved D04/D07/D08 decisions. No genuine identity/code/contact record may enter this test. | NOT_RUN |
| H04-OPS | Reproduce clean startup, controlled outage and restart, real PostgreSQL backup/restore, restore fences, cleanup, dependency locks/digests, operator access and incident runbook; examine resource-exhaustion/saturation gap and D01–D06/D10 ownership, budget and operator decisions. | NOT_RUN |
| H04-GOV | Verify reviewer independence and recorded dissent, exact head/base/config/run evidence, critical finding dispositions and scoped human decision. Do not allow T04 engineering PASS to silently grant ACCOUNT-1/T05/deployment/merge authority. | NOT_RUN |

## Minimum redacted evidence record

For each human test or review, record a separate versioned, immutable-in-review entry, using this structure (a format suggestion, **not** evidence that someone has run it):

```text
gate_case_id:
status: NOT_RUN | BLOCKED | FAIL | PASS
scope: SYNTHETIC_ONLY
repo / pr / tested_head / base_sha / workflow_id-or-sha:
reviewer_id_or_role: [assigned by human]
reviewer_independent_from_implementation: [human-confirmed true/false]
utc_time:
environment: [generic device/browser/OS version or runtime, no personal identifiers]
procedure_id / expected / observed:
evidence_refs: [sanitized, access-controlled pointers only]
finding_ids / severity / disposition:
dissent_or_limitations:
human_decision_and_scope:
```

Do **not** save screenshots with identities, credential values, cookies, tokens, recovery codes, device identifiers, phone numbers, emails, private DNS secrets or unredacted browser traffic. A CI result, AI summary, PR comment or document alone is never a substituted human signature.

## Fail-closed decision

- **AUTOMATED ENGINEERING PASS**: established only for the frozen synthetic CI head above.
- **T04 HUMAN ACCEPTANCE**: HOLD until applicable physical-device/manual accessibility cases and independent SEC/PRIV/OPS/GOV reviews are completed with attributable evidence; mark unavailable scenarios BLOCKED, not waived. Any FAIL/unresolved blocker => HOLD.
- **ACCOUNT-1 / T05–T08 / real identity / real consent / contact / distribution / payment / production / merge**: all separate, explicitly authorized human gates; **remain HOLD regardless of T04 review outcome**.
- No reviewer has been appointed, no physical Android/manual screen-reader session has been performed here, and no hosting/network or real account has been created.

## Next legal transition

A human project owner appoints qualified independent reviewers, resolves the safe synthetic physical test path as a separate reviewed change if needed, records real manual observations, adjudicates findings and makes a signed scoped decision. Preserve rejected and conflicting evidence; no automatic authority follows from this file.
