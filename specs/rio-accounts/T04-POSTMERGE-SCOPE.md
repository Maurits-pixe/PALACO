# RIO T04 — Post-merge source scope and acceptance separation

### Status
POST-MERGE GOVERNANCE RECONCILIATION / SYNTHETIC SOURCE-GUARD CANDIDATE / HUMAN ACCEPTANCE HOLD.

### Last Updated
2026-10-14

## Observation and controlling distinctions

[PR #49](https://github.com/Maurits-pixe/PALACO/pull/49) was merged by the GitHub account `Maurits-pixe` on 2026-10-13 at 23:38:11 UTC (14 October, 01:38:11 Europe/Amsterdam). The merge commit is [`facf4f2c5bd0898da1dcf80bb80ec861aa70e062`](https://github.com/Maurits-pixe/PALACO/commit/facf4f2c5bd0898da1dcf80bb80ec861aa70e062). It followed prior engineering CI PASS on frozen candidate head `202ba6cba22fa07829c4595dd79216dcd4580ed1`. GitHub returned zero PR review records; the [independent T04 review task #50](https://github.com/Maurits-pixe/PALACO/issues/50) is still open. Neither a merge click nor successful engineering CI is evidence that independent accessibility, security, privacy and operations acceptances occurred.

Post-merge, a [GitHub Pages build/deployment #38485445641](https://github.com/Maurits-pixe/PALACO/actions/runs/38485445641) succeeded. Its publication artifact content and any effects on external Render workspaces have **not** been assessed here. The [GO-10 Foundation Audit #38485445611](https://github.com/Maurits-pixe/PALACO/actions/runs/38485445611) failed with PVS-001 workspace members mismatch, although [an earlier base-run #38067451313](https://github.com/Maurits-pixe/PALACO/actions/runs/38067451313) had also failed; new regression causality is not established. Record the merge, deployment scope and audit findings in [issue #52](https://github.com/Maurits-pixe/PALACO/issues/52).

The source merge changed version control state, **not** the system's constitutional approval state:

```text
SOURCE_MERGED ≠ T04_HUMAN_ACCEPTED
CI_PASS ≠ IDENTITY_AUTHORIZED
PAGES_DEPLOYMENT ≠ RIO_ACCOUNT_OPERATIONAL
NO_REVIEW_RECORD ≠ AUTHORITY_GRANTED
ACCOUNT-1 = HOLD
CONTACT = HOLD
PRODUCTION / PAYMENT / INVITATION = HOLD
```

## Automated static boundary detector

`verification/rio-accounts/postmerge_scope.py` checks 15 narrowly specified, **source-level** constraints on a candidate checkout. Its negative unit tests are in `verification/rio-accounts/test_postmerge_scope.py`. This is deliberately a drift sentinel, **not a security audit** and not proof that actual runtime deployments or other code paths are safe.

The checks cover fixed localhost HTTPS BFF origin and synthetic IdP issuer, explicit `SYNTHETIC_ONLY` mode rejection of other modes, listener bound to `127.0.0.1:8088`, HOLD banner, closed `/api/status`, own-session-bound `/api/me` and fixed account/authority/contact flags, actor-bound consent receipt, synthetic fixture issuer/callback, disabled registration/recovery/email login, human HOLD document, and read-only GitHub Actions token permission in the synthetic workflow. Missing or drifted literals fail; stricter deployment/runtime assurance still needs qualified independent human review.

From a candidate checkout:

```sh
python -m unittest discover -s verification/rio-accounts -p test_postmerge_scope.py
python verification/rio-accounts/postmerge_scope.py
```

The full RIO synthetic workflow is configured to repeat these checks on a PR. The guard emits only controlled check IDs and a source-scope PASS/FAIL. It **always** reports `humanAcceptance=HOLD` and `deploymentAcceptance=HOLD`, including when all 15 checks pass. A green status is not merge permission or real account authorization. Enforcement against merging additionally requires a separately human-approved required-status rule or branch protection; this new draft does not change repository settings.

## Next decisions

The source is already merged into `main`; the next human decision concerns provenance and whether to retain the merged code, commission a separately reviewed rollback, or authorize a new scoped change. Never silently revert, force-push, grant account access, provision environments or treat a GitHub Pages deployment as evidence of working RIO contact. [Issue #50](https://github.com/Maurits-pixe/PALACO/issues/50) remains the separate T04 human review gate; [issue #51](https://github.com/Maurits-pixe/PALACO/issues/51) retains unresolved intermittent login investigation. This post-merge guard is submitted on a **new draft branch**, with no production deployment or account activation.
