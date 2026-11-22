# PALACO — offline PR HOLD assessor v7 (candidate)

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

## V4 deterministic advisory proof identifiers

Each advisory output now includes three identifiers derived with SHA-256 over
canonical JSON (UTF-8, lexicographically sorted object keys, no insignificant
whitespace, and no NaN/Infinity):

- \`manifest_sha256\`: a digest of a separately versioned evidence manifest
  containing repository, candidate head SHA and a sorted sequence of evidence
  records; null if evidence cannot be represented as a valid manifest.
- \`snapshot_sha256\`: digest of the complete untrusted input snapshot.
- \`report_sha256\`: digest of the output report before adding this field,
  including the two preceding identifiers and HOLD/DENY result.

Reordering object keys or evidence entries does not change the manifest hash.
Changing the submitted input changes the snapshot hash (except for negligible
cryptographic collision probability). Hashes **do not prove who produced the
data**: there are no signatures, trusted timestamps, independent reviewers,
or authenticated attestations in v4. The SHA-256 digests cannot be used as
authorization. GO-13 remains HOLD; no CI pass or manifest field grants authority.

This candidate also pins \`actions/checkout\` to a Git commit SHA in GO-20 CI to
meet repository workflow supply-chain requirements.

## V5 independently keyed report-chain verification

The new `scripts/pr_attestation_chain.py` verifier checks a sequence of
HOLD/DENY reports, their report SHA-256 fingerprints, linked predecessor
entry SHA-256 fingerprints and detached Ed25519 signatures. It accepts a
**separate trust-store file** mapping reviewer key identifiers to raw
Ed25519 public keys as 64 lowercase hexadecimal characters.

```sh
python3 scripts/pr_attestation_chain.py ./chain.json --trust-store ./trusted-reviewers.json
python3 -m unittest discover -s tests -p 'test_pr_attestation_chain.py' -v
```

A chain has `schema: "palaco.pr-attestation-chain.v1"` and a nonempty `entries`
list (maximum 256). Each entry provides `sequence` (starting at zero),
`previous_entry_sha256` (64 zeroes for the first entry), `report` (the
exact v4 HOLD/DENY output), `key_id`, `signature_ed25519_hex` (128 hex
characters) and `entry_sha256`. The signed statement contains
`schema: "palaco.pr-attestation-statement.v1"`, the entry sequence,
predecessor hash and the report SHA-256. Sign Ed25519 over the **32 raw
bytes of SHA-256(canonical JSON statement)**, not over the JSON text.
The entry SHA-256 covers all its fields except `entry_sha256`.

Ed25519 verification uses the optional, independently maintained Python
`cryptography` package; absence of that package is an explicit
`crypto_backend_unavailable` failure. The project does not install a
cryptography dependency automatically, and no homemade signature primitive
or fake signature verification is used. The optional success-path signature
test is skipped on runners without this package; negative chain tests
still run. A separate reviewed dependency/pinning decision is required
before treating cryptographic checks as a required CI gate.

The trust-store MUST be provisioned independently of the untrusted chain.
Successful signature verification only establishes possession of a private
key matching a trusted public key, not a human review decision or the
reviewer's organizational authority. Trust-store lifecycle, key revocation,
authenticated identity binding, time semantics and full artifact origin are
not established. No verifier result authorizes execution, production,
release or a GitHub merge; GO-13 stays HOLD.

## V6 — externe sleutelstatus en replaycontrole

Nieuwe offline, alleen-lezen beleidscontrole:
`scripts/pr_attestation_policy.py`. Deze bouwt voort op de v5-verificatie
van Ed25519-handtekeningen en rapportketens. Alle gegevens moeten
**onafhankelijk** van de te controleren rapportketen beschikbaar zijn.

```sh
python3 scripts/pr_attestation_policy.py chain.json \
  --registry trusted-key-registry.json \
  --replay-journal trusted-replay-journal.json
python3 -m unittest discover -s tests -p 'test_pr_attestation_policy.py' -v
```

Vertrouwensregister (voorbeeld, fictieve sleutel):

```json
{
  "schema": "palaco.pr-trust-registry.v1",
  "keys": {
    "reviewer-a": {
      "public_key_hex": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "status": "active",
      "valid_from_sequence": 0,
      "valid_until_sequence": null
    }
  }
}
```

Replayregister, onafhankelijk vastgelegd:

```json
{
  "schema": "palaco.pr-replay-journal.v1",
  "consumed_entry_sha256": []
}
```

De beleidscontrole controleert onbekende of ingetrokken sleutels, grenzen van
toegestane indexnummers, reeds geregistreerde entry-digests, dubbele vermeldingen
in het replayregister en de verplichte v5-rapportketenverificatie. Een replaymatch,
ontbrekend register of ongeldige structuur resulteert in `policy_valid: false`.

**Begrenzing:** de reeksnummers zijn geen tijdstempels en kunnen geen
historisch sleutellidmaatschap bewijzen. Dit is een uitsluitend lokale
momentopname. De tool schrijft **geen** replaystatus terug; gelijktijdige
controleurs zonder gezamenlijk atomair register kunnen dezelfde nieuwe entry
tweemaal accepteren. Een veilige productie-implementatie heeft een onafhankelijk
geauthenticeerd register, actuele intrekkingsgegevens, commitbinding,
atomair verbruik van replaytokens, en een menselijke governancebeslissing nodig.
`policy_valid: true` blijft uitsluitend een technisch oordeel, nooit release-
of uitvoeringsautorisatie. GO-13 blijft HOLD en alle uitkomsten houden
`decision: HOLD` en `authorization: DENY`.

## V7 — ondertekende registermomentopname en alleen-lezen CAS-voorstel

`scripts/pr_replay_preflight.py` verwacht een onafhankelijk verankerde
Ed25519-rootsleutel, een ondertekende snapshot van **zowel** het sleutelregister
als het replayregister, en een expliciet verwacht revisienummer.

```sh
python3 scripts/pr_replay_preflight.py chain.json \
  --signed-state signed-state.json \
  --root-public-key <64-lowercase-hex> \
  --expected-revision 4
python3 -m unittest discover -s tests -p 'test_pr_replay_preflight.py' -v
```

De snapshot heeft `payload` en `signature_ed25519_hex`. De payload omvat
`schema: palaco.pr-signed-state.v1`, `revision`, `registry` en `journal`.
De handtekening is Ed25519 over de 32 ruwe bytes van SHA-256 van de
gecanoniseerde statement `{"schema":"palaco.pr-state-signature.v1",
"payload_sha256":"<digest>"}`. De rootsleutel moet uit een **onafhankelijke,
vertrouwde bron** komen; een sleutel meegeleverd in de te verifiëren snapshot
is niet voldoende.

Bij geldige snapshot, onveranderd revisienummer en geslaagde v6-beleidstoets
maakt de verifier uitsluitend een voorstel met de verwachte revisie,
`expected_state_sha256`, voorgestelde nieuwe journalhash en
`atomic_commit_performed: false`. De verifier schrijft niets terug.

**Dit is geen daadwerkelijke CAS of atomaire transactie.** Een latere backend
moet onder één databasevergrendeling de geauthenticeerde actuele staat,
revisie en hash vergelijken, alle voorgestelde entrydigests opnieuw tegen
het actuele replayregister toetsen, en pas daarna atomair opslaan.
Snapshotversheid, sleutelintrekking, rollbackbescherming en een formele
human-authority-verificatie vallen nog buiten dit lokale ontwerp.
Alle uitkomsten houden **HOLD / DENY**.
