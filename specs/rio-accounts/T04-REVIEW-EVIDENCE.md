# T04 — Safe structured evidence intake (synthetic mobile)

### Status
ENGINEERING REVIEW INTAKE CANDIDATE / HUMAN ACCEPTANCE HOLD / SYNTHETIC_ONLY. This is not a signoff process or a source of authority.

### Last Updated
2026-10-14

## Intent

An independent reviewer can report the **status** of each required manual or security review without copying names, credentials, browser traces, screenshots, device identifiers, contact details, or secrets into Git. The accompanying deterministic Python validator enforces a strict shape and rejects fabricated completeness. It cannot independently verify human qualifications, timestamps, independence, physical device use, accessibility quality, or authenticity of the actual observations.

Source: [T04 independent acceptance protocol](T04-ACCEPTANCE-GATE.md); tracking: [issue #50](https://github.com/Maurits-pixe/PALACO/issues/50). The latest full CI PASS **before this intake change** belongs to `ec751fc943cf5de3a42736958f8cee31a6a9d53d`; later commits need their own checks. No evidence claims can be transferred across HEAD/BASE/config without assessment.

## Contract and operator sequence

A structural template lives at `verification/rio-accounts/review/t04-review-template.json`. It intentionally contains five `BLOCKED` physical-Android cases and six `NOT_RUN` manual/review cases, with all personal and production authority `HOLD`. Only `SYNTHETIC_ONLY` is supported. The operator may create a *local* candidate record containing the same exact key set; store the actual privileged evidence, if any, separately under approved owner-controlled access, not in the PR.

For a local redacted review record (no credentials or personal information):

```sh
python verification/rio-accounts/review_gate.py verification/rio-accounts/review/t04-review-template.json
python -m unittest discover -s verification/rio-accounts -p test_review_gate.py
```

The validator accepts exactly 11 known case IDs: `H04-A01`…`H04-A07`, `H04-SEC`, `H04-PRIV`, `H04-OPS`, `H04-GOV`. Each case carries a status (`NOT_RUN`, `BLOCKED`, `FAIL`, `PASS`), a controlled reason, a reviewer **role** (not identity), an explicit independence-attestation flag, zero or more opaque redacted evidence IDs (`EVD-…`), and finding IDs (`FND-…`). A `PASS` record must have the correct reviewer role, independence attestation, evidence ID and zero open findings; a physical case also needs a separate *human attestation* that a trusted synthetic-only access path was authorized. This structure is **not proof** that the human review, authorization or device test actually happened. A `FAIL` must carry a finding ID and evidence reference; missing reviews remain clearly `NOT_RUN` or `BLOCKED`.

The output is a bounded fixed-schema count and **always returns** `humanAcceptance=HOLD`, `physicalAndroidVerified=false`, `independentReviewAccepted=false` — including when all 11 records claim PASS. Rejecting a record prints only `RIO_T04_REVIEW_RECORD REJECTED`, never source data. The validator rejects extra fields, duplicated JSON keys, non-enumerated reasons/statuses, raw URLs, and inputs over 16 KiB. It does not store, publish, upload or sign the submitted record.

No actual human acceptance may be inferred from a generated checklist, a GitHub Actions green check, a reported reviewer role, a reviewer claim, an AI-generated summary or this machine-checkable template. Independent review, physical-device test configuration, the human final decision, real accounts, contact, hosting, integration, merging and production remain distinct gates, all **HOLD**.

## Reviewer recording boundary

Only the designated human owner can arrange qualified reviewers and approve any physical-device environment. In the separate controlled review file or system, keep the real tester/reviewer identity, date, competence/conflict assessment, device OS+browser version (never device serial or contact identifier), test steps and observed results, scoped evidence pointers, findings and signatures. Protect and minimize that information; never transfer it into this repository or generic CI logs. A successful scripted check on a fabricated JSON sample is **never** acceptance.
