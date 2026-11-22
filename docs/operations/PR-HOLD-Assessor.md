# PALACO — offline PR HOLD assessor v3 (candidate)

Opt-in, Python standard-library only. Reads a local JSON snapshot and emits a deterministic, machine-readable advisory assessment. No network requests, secrets, GitHub status changes, approvals, or deployments.

## Run

```sh
python3 -m unittest discover -s tests -p 'test_pr_hold_assessor.py'
python3 scripts/pr_hold_assessor.py path/to/snapshot.json --evidence-root path/to/evidence
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
      "artifact_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "path": "proof.txt"
    }
  ],
  "go13_release_authorized": false
}
```

The `evidence` entries bind an artifact digest, root-relative POSIX-style path and type to a head SHA. With `--evidence-root`, the assessor **reads and hashes each local regular file** (maximum 16 MiB) and compares the SHA-256 digest. It rejects absolute paths, `..` traversal, symlinks, and non-regular files. Secure traversal needs O_NOFOLLOW and directory-relative opening; if unavailable (including some Windows environments), it fails closed with `secure_file_open_unsupported`. Without `--evidence-root`, it emits `evidence_not_verified` and `technical_inputs_complete: false`. This is file-integrity verification, **not proof of source authenticity, signature validity, GitHub check status, or release authority**. The input may be fabricated and cannot be used as an attestation. Duplicate JSON keys and duplicate evidence digests are rejected; legacy string-only evidence records are rejected. Files can change concurrently; a match proves the bytes read during this check, not their persistence or provenance. SHA-1 head identifiers require 40 lowercase hex digits; SHA-256 artifacts require 64 lowercase hex digits.

Valid check states: `success`, `failure`, `pending`, `missing`; reviews: `approved`, `changes_requested`, `pending`, `missing`. Any non-successful check produces a reason. `technical_inputs_complete` is an advisory statement about local input consistency, not verified trust.

**Every output keeps `decision: HOLD` and `authorization: DENY`.** GO-13 remains HOLD. No merge or production promotion is permitted by this tool. Independent human review and verified evidence are separate requirements.
