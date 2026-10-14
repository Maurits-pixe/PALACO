# T04 — Focused synthetic OIDC readiness investigation

Status: ENGINEERING INVESTIGATION / SYNTHETIC_ONLY. [Issue #51](https://github.com/Maurits-pixe/PALACO/issues/51) remains open; a unique cause is not established.

The baseline `202ba6cba22fa07829c4595dd79216dcd4580ed1` passed both full account workflows. Earlier account-readiness failures are preserved as negative evidence. A successful callback to the home page occurs after the server commits the synthetic session. The page then reads its own account and its consent receipt; a failed or uncertain receipt check can clear the account display again. Therefore a missing displayed identity does not by itself identify an OIDC verifier failure.

## Bounded repetition

After the existing real database-outage and controlled-recovery case, CI executes exactly eight repetitions of `RIO-DURABLE-01`. Each uses fresh browser contexts for alpha, alpha peer and beta and actual Keycloak sign-in, private session saving, cookie and own-account checks. This adds 24 fictional logins before ordinary preparation and the existing restart, revocation, mobile and backup/restore tests.

The [Playwright CLI](https://playwright.dev/docs/test-cli) distinguishes repetition from retry. The command keeps retries at zero, one worker and the existing timeouts; its first failure stops the probe and fails CI. It never reruns a failed action silently. Each probe round exclusively creates its private snapshot, verifies the saved values, closes its contexts and removes only the snapshot it created. A pre-existing snapshot remains protected: a failed exclusive create never authorizes its removal. Ordinary preparation then creates and retains its own fresh snapshot, so the later revocation proof does not use older probe sessions.

The probe retains the 30-second idle and 60-second absolute session limits, fixed loopback origins, purpose and owner checks, current test assertions, bounded database records, private credentials and final cleanup. It creates no real account, contact, device trust, hosting resource or execution authority.

## Failure evidence and interpretation

Only an allowed synthetic actor/stage/page category, known account/consent endpoint statuses, request-failure booleans and a fixed feedback category may enter sanitized failure evidence. URLs, headers, bodies, credential values, raw DOM text and raw errors remain private.

Eight successful repetitions are eight observations in this fixture. They are not a statistical reliability claim, an independent acceptance, a physical-phone test or a cause-specific repair. The original issue remains open until failure evidence supports a concrete diagnosis and an appropriate regression check. Human acceptance, ACCOUNT-1, T05–T08, merge and production retain their separate HOLD gates.
