# CI boundary-consumer correction v0.14

PR: Maurits-pixe/PALACO#106. Failed candidate:
1ce1d1de25c4cb98fe8b451fa2bc9a87a2c340d3.
RIO run: 41903008556; job: 126830132377.

Observed: all 145 Python checks passed; the Rust library had 38 passing and four
explicitly ignored tests, with a separate integration test also passing. Formatting,
Clippy, build and docs passed. Actual synthetic storage and consent HTTP checks
passed. The real OIDC browser job failed in cases RIO-E2E-01/04/05 at the visible
account assertion. Subsequent browser/restart/backup stages were skipped.

Cause: this candidate added personalAccountControl to /api/me but left the
frontend validMe exact-key schema and two browser schema assertions on the older
response shape. Login returned to the BFF, but the frontend rejected the new
response. This is a candidate regression, not evidence of invalid credentials or
an OIDC-provider failure. Generic provider diagnostic category booleans do not
supersede the concrete failing assertion and inspected strict-schema mismatch.

Correction: update validMe to require the additional field and validate its exact
five-key refusal payload. Strong authentication must be UNKNOWN, lifecycle
power NONE and activationEligible exactly false. Missing, malformed, promoted or
extra nested claims still refuse. Update both OIDC/durable response assertions to
require the same exact refusal metadata.

The existing RIO-E2E-01 real-browser scenario now also intercepts /api/me with null,
promoted-activation, promoted-authority, promoted-authentication and extra-field
boundaries. It requires the visible account to close, then restores the genuine
response and requires own-account visibility. No retry, assertion removal, schema
wildcard, token logging or production access is introduced.

Local: Node syntax checks and existing Python checks pass. These do not establish
real browser PASS. A new commit/run is required; the failed run remains preserved.
Actual Rust/service success applies only to the named old head, pending rerun for
the correction. Production/ACCOUNT-1 HOLD; no merge or activation authorized.
