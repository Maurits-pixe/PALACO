# Visible personal-access boundary v0.1 — synthetic UI

Object: reference slice v0.16 and the existing RIO own-test-account screen.
No account activation, new endpoint, contact action or authority is added.

## User-visible outcome

After a valid, strictly checked /api/me response, the account card includes a
named Persoonlijke toegang region with the status Persoonlijke toegang blijft
gesloten. It explains that extra safety checks and an authorized human approval
are needed for personal access. This describes the actual existing refusal;
it does not claim that a review is pending, assign a reviewer or offer admission.

The region has no links, inputs or buttons. It cannot grant authority and does
not add keyboard stops. A level-three heading labels the section; the status is
polite/atomic for assistive technology. The existing colors, focus behavior and
responsive card layout are retained. No internal enum, token or actor mandate
is exposed as product text.

## Visibility and state

The region starts hidden in HTML. renderControls shows it only in the existing
authenticated UI phase with a current CSRF-bound own session; that phase follows
validMe's exact refusal-contract validation. Clearing personal state hides it and
clears its dynamic status text. Anonymous, invalid, unavailable, expired and
logged-out states therefore do not retain visible session-bound messaging.

The notice stays closed after synthetic session consent is granted or revoked.
Consent and OIDC login still cannot satisfy strong-authentication, human review
or activation gates. The generic synthetic boundary notice remains elsewhere on
the page, including before login; the new region contextualizes it for the signed-
in test account rather than displaying any personal lifecycle claim.

## Verification scope

Existing real-OIDC browser tests now assert the named visible region after login,
its closed status/no controls, and its disappearance after invalid metadata,
invalid credentials/session, logout/logout-all and expiry. Generic API readback
helpers remain API-only: they do not assume that manually swapped cookies have
automatically repaired an already closed UI.

The existing mobile native-semantics scenario checks the named region, polite
status, absence of actions and unchanged closed state after consent. Its existing
keyboard and 320px reflow checks run with the additional content. These are
browser/emulation checks, not physical-device or human accessibility acceptance.

Local Node syntax, HTML ID/default-hidden/named-region checks and Python tests
pass. Actual browser results must be collected for the new commit; the previous
head's green run is not proof for these source changes. Production/ACCOUNT-1 HOLD.

AI review: TRIAS — refusal-only presentation; no new grant or public action.
ORACLE — static/local checks are separate from pending new-head browser CI and
unexecuted human accessibility review. MENTOR — require the complete existing
synthetic CI before assessing this UI candidate for human review.
