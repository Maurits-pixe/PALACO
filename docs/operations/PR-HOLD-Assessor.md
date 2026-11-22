# PALACO — offline PR HOLD assessor (candidate)

This opt-in, standard-library-only tool reads a **local synthetic or independently
collected JSON snapshot** and emits a deterministic, machine-readable assessment.
It does not query GitHub, approve a PR, validate cryptographic signatures, grant
privileges, modify CI, or authorize deployments. It is not a trusted attestation.

## Run

```bash
python3 -m unittest discover -s tests -p 'test_pr_hold_assessor.py'
python3 scripts/pr_hold_assessor.py path/to/snapshot.json
```

Example snapshot (replace the illustrative SHA with the real, independently
verified head commit before any human review):

```json
{
  "repository": "Maurits-pixe/PALACO",
  "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "checks": {"unit": "success", "security": "pending"},
  "reviews": "pending",
  "evidence": ["synthetic-local-test"],
  "go13_release_authorized": false
}
```

Valid check states: `success`, `failure`, `pending`, `missing`.
Valid review states: `approved`, `changes_requested`, `pending`, `missing`.
Missing, invalid, or failed fields are listed under `reasons`. The output
always contains `decision: HOLD` and `authorization: DENY`, including when
`technical_inputs_complete` is true. No automated promotion exists.

**Governance:** GO-13 remains HOLD. A separate authorized human review, external
evidence verification, and documented approval would be needed before any
release. This candidate must not be represented as an effective authorization
or as proof that actual GitHub checks have passed.
