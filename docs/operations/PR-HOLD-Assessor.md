# PALACO — offline PR HOLD assessor v2 (candidate)

Opt-in, Python standard-library only. Reads a local JSON snapshot and emits a deterministic, machine-readable advisory assessment. No network requests, secrets, GitHub status changes, approvals, or deployments.

## Run

```sh
python3 -m unittest discover -s tests -p 'test_pr_hold_assessor.py'
python3 scripts/pr_hold_assessor.py path/to/snapshot.json
```

Example synthetic input:

```json
{
  "repository": "Maurits-pixe/PALACO",
  "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "checks": {"unit": "success", "security": "pending"},
  "reviews": "pending",
  "evidence": [
    {
      "kind": "unit-test-log",
      "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    }
  ],
  "go13_release_authorized": false
}
```

The `evidence` entries bind an artifact digest and type to a head SHA. The assessor checks **only the syntax and internal consistency** of those fields. It does not hash files, authenticate the source, verify signatures, confirm a real GitHub check, or establish actual authorization. The input may be fabricated and cannot be used as an attestation. Duplicate JSON keys and duplicate evidence digests are rejected; legacy string-only evidence records are rejected. SHA-1 head identifiers require 40 lowercase hex digits; SHA-256 artifacts require 64 lowercase hex digits.

Valid check states: `success`, `failure`, `pending`, `missing`; reviews: `approved`, `changes_requested`, `pending`, `missing`. Any non-successful check produces a reason. `technical_inputs_complete` is an advisory statement about local input consistency, not verified trust.

**Every output keeps `decision: HOLD` and `authorization: DENY`.** GO-13 remains HOLD. No merge or production promotion is permitted by this tool. Independent human review and verified evidence are separate requirements.
