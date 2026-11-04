# Hannie validation-deadline candidate

Separate synthetic implementation of the explicitly adopted profile in CONTRACT.md. An exact opted-in command can persist after write-consent expiry; this does not satisfy or replace historical D-013 evidence. New independent read authority is required to release contents.

Linux, Node 24.14.1 or 24.19.0, gcc, glibc, /usr/bin/flock; no npm dependencies. Run `node tools/run-evidence.mjs` from this directory. Each run creates a new evidence/hara/validation-deadline/runs/<UUID> with source hashes, TAP and native/process traces. These test fixtures are not product permission flags.

No integration/production/merge release. New supervisor recovery, restore/trust epoch and genuine time/admission authority remain outside the demonstrated synthetic scope. See CONTRACT.md and the separate evidence report.

`src/client.mjs` provides pure `prepareConsent`, `recordConsentSelection` and `presentResult` helpers. Consent selection remains unauthenticated and cannot execute or provision anything. The evidence runner records 13 client controls separately from the 24 runtime controls. No web renderer, real owner authentication or live client integration is supplied.
