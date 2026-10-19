# IIP-1 — Identity Issuance Protocol

**Status:** Open Identity Gate · draft v0.2 · reference implementation only

## Purpose and boundary

IIP-1 evaluates whether a provisional dossier may proceed through identity
review. Account activation is a prerequisite, not an identity decision. Identity
issuance and operational authority are separate decisions:

`ACCOUNT ACTIVE → IDENTITY REVIEW → ISSUANCE REVIEW → IDENTITY ISSUANCE`

`IDENTITY ISSUED ≠ AUTHORITY GRANTED`

The reference evaluator in `palaco-la::identity_issuance` evaluates a strict,
versioned synthetic request. It does not connect to account services, dossiers,
an issuer registry, consent storage, or a provenance anchor. Input evidence and
issuer assertions are not authenticated. A positive result is a test of the
contract only; it does not issue a credential, create authority, or activate
anything.

## Review gates

All evidence references include an explicit version. Reviews fail closed unless
the request provides:

1. An active, unblocked, unrevoked account and a provisional dossier.
2. Subject confirmation independent of mailbox control.
3. Owner confirmation bound to that dossier and subject.
4. Current, unrevoked consent for the requested scope, not expired at evaluation.
5. Provenance bound to a non-empty source state whose SHA-256 digest matches,
   with identifiable source and anchor references and non-empty history.
6. An issuance request and issuer evidence matching the requested basis and
   scope, with an active, unrevoked, non-expired issuer assertion.

These checks produce review states, `identity_validated`, and at most
`SYNTHETIC_APPROVAL_ONLY`. The synthetic booleans are fixture assertions, not
proof of subject identity, ownership, consent, provenance anchoring, or issuer
authority.

The reference contract hashes the exact UTF-8 bytes of `source_state`; it does
not define canonical encoding or authenticate the claimed anchor. A production
contract still needs an approved canonical byte format and verifiable trust
chain.

## Not implemented

The reference evaluator always returns:

- `identity_issued = false`
- `identity_manifest_created = false`
- `identity_seal_created = false`
- `authority_granted = false`

It does not create the formal identity manifest or cryptographic seal described
by the draft. No production issuer, source-state anchor, identity registry, or
revocation service is provisioned. Therefore existing dossiers remain
`PROVISIONAL DOSSIER RECORD`; administrative identifiers, including 5CRIPTIE
codes, are not issued identities or authority.

The production gate remains HOLD until evidence authenticity, current consent,
anchored provenance, issuer authorization, durable review records, revocation,
and independent security/governance approval are defined and implemented.

## Temporary development startup continuation

`evaluate_development_bootstrap` is compiled only when Rust debug assertions are
enabled and accepts only the `RIO_MESSAGE_SERVICE_TEST` purpose. It is opt-in for
each startup request; without opt-in it remains blocked. With opt-in it returns
`CONTINUE_RESTRICTED`, while explicitly keeping 5CRIPTIE evidence `UNVERIFIED`,
identity issuance disabled, authority disabled, and external message delivery
disabled. It does not alter IIP review or make an authentication claim.

This repository contains no live RIO message service or delivery path. The
development API only provides a restricted startup decision for a test
integration to consume; it does not itself start or connect to a service. It is
absent from optimized release builds and is not connected to production startup
or authentication.

### Provisional RIO test access declaration

The project owner provisionally designates these two accounts as eligible to
request the restricted development startup continuation for RIO message-service
testing:

- `mauritsvangeen@hotmail.com`
- `iii6v9@gmail.com`

This designation is limited to the development test purpose above. It grants no
5CRIPTIE evidence verification, identity issuance, operative authority, or
external message delivery. It is a governance record only: the current helper
does not authenticate users or enforce this account list. Email text alone is
not proof of account control or identity. Before relying on this designation,
an authenticated account provider must bind verified account identifiers to
the eligibility policy, and the test integration must enforce that policy
server-side. Until then, this document must not be treated as a working access
control or permission to connect to a live service.

## Verification

Run the reference contract tests with:

```sh
cargo test -p palaco-la --test iip1_reference
```
