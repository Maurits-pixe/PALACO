# PALACO — offline PR HOLD assessor v15 (candidate)

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

## V8 — transactioneel replaycontract (simulatie; niet persistent)

`scripts/pr_replay_transaction_contract.py` bevat een **zuivere,
alleen-lezen** referentiefunctie `evaluate_transition(current, proposal)`.
Deze modelleert de voorwaarden voor een toekomstige transactionele
compare-and-swap (CAS) replayopslag, maar opent geen databaseverbinding,
plaatst geen vergrendeling en schrijft geen gegevens weg.

```sh
python3 -m unittest discover -s tests -p 'test_pr_replay_transaction_contract.py' -v
```

Het contract vereist tegelijk:

- Exact gespecificeerde, geldige huidige staat en voorgestelde transactie.
- Geldige SHA-256-binding van het voorstel aan de **ongewijzigde**
  verwachte revisie en gehele huidige toestand.
- Geen eerder verbruikte of dubbele ontvangsthashes.
- Een canoniek gesorteerd nieuw replayregister dat exact overeenkomt met
  de huidige hashes plus de nieuwe hashes.
- Overeenstemmende hash van het voorgestelde nieuwe replayregister.
- Maximale registergrootte van 10.000 hashes en veilige 64-bits revisiegrens.
- Een expliciete `atomic_commit_performed: false` in het voorstel.

Alleen als alle voorwaarden gelden retourneert het contract een
`proposed_next_state` met `revision + 1` en een bijbehorende hash.
Ook in dat geval blijven `state_persisted: false`,
`atomic_commit_performed: false`, `decision: HOLD` en
`authorization: DENY`.

**Vereiste toekomstige backendsemantiek:** verkrijg binnen één
serialiseerbare transactie een exclusieve toestandvergrendeling; laad
de actuele registerinhoud; verifieer de vertrouwde identiteit en
autorisatie buiten dit simulatiemodel; controleer revisie en toestandhash;
controleer opnieuw iedere hash op eerder verbruik; schrijf het nieuwe
register en de nieuwe revisie samen atomair weg; commit éénmaal of
rollback volledig. Verleen geen uitvoeringsbevoegdheid op basis van
het feit dat het simulatiecontract slaagt. De code in v8 **implementeert
deze databasehandelingen niet**. GO-13 blijft HOLD.

## V9 — deterministische concurrentie- en rollback-simulatie

`scripts/pr_replay_interleavings.py` voegt een geïsoleerde in-memory
referentiemachine toe bovenop het v8-transitiecontract. De machine bootst
**beide mogelijke seriële volgordes** van twee concurrerende voorstellen na.
Twee voorstellen voor dezelfde oorspronkelijke revisie kunnen elk afzonderlijk
geldig zijn, maar na een gesimuleerde eerste commit wordt het tweede
afgewezen wegens revisie- of toestandconflict.

```sh
python3 -m unittest discover -s tests -p 'test_pr_replay_interleavings.py' -v
```

De testharness bevat vaste foutinjectiepunten (`before_cas`,
`after_validation`, `before_commit`). Bij een geïnjecteerde fout blijft
de complete simulatiestaat ongewijzigd en verschijnt geen ontvangstbewijs.
Een geslaagde *gesimuleerde* overgang verhoogt alleen de revisie in het
geïsoleerde geheugenmodel en voegt één gemarkeerd simulatiebewijs toe.
Alle resultaten behouden `decision: HOLD`,
`authorization: DENY` en `database_commit_performed: false`.

**Beperkingen:** dit is geen gelijktijdige threaded load-test en geen
databaseverificatie. De harness onderzoekt twee seriële interleavings;
hij bewijst niets over netwerkfouten, procescrashes, lockbeheer,
database-isolatieniveaus, multi-writerconsistentie of duurzame opslag.
Geen GitHub-merge, autorisatie of productie-uitvoering wordt geactiveerd.
Een echte database-implementatie vereist onafhankelijke integratietests,
concurrerende transacties en crash-/herstelproeven.

## V10 — SQLite-integratieharness in een tijdelijke testdatabase

`scripts/pr_replay_sqlite_harness.py` bevat een afgesloten SQLite-harness
die **uitsluitend zelf een nieuwe tijdelijke database** aanmaakt. Er is
geen parameter voor een bestaande database, geen externe verbinding en
geen productieconfiguratie. De database wordt na de tests opgeruimd.

```sh
python3 -m unittest discover -s tests -p 'test_pr_replay_sqlite_harness.py' -v
```

De harness opent voor iedere schrijfpoging een afzonderlijke verbinding
en begint met `BEGIN IMMEDIATE`. Binnen die transactie worden de
huidige toestand en de v8-voorwaarden gelezen en opnieuw gecontroleerd.
De toestand en afzonderlijk uniek geïndexeerde ontvangsthashes worden
samen ingevoegd, gevolgd door één `COMMIT`. Bij fouten en geïnjecteerde
fouten na de toestandswijziging of na ontvangstregistratie volgt
`ROLLBACK`. De tests controleren dat géén deelwijziging blijft staan.

De tests behandelen daarnaast twee daadwerkelijk concurrerende lokale
threads, hergebruik van dezelfde hash, heropening van SQLite-verbindingen,
afwijkende revisies en een herhaalde poging na rollback.

**Belangrijke grens:** dit verifieert alleen de tijdelijke SQLite-fixture.
Het is geen integratie met PALACO MONO/Supabase/PostgreSQL, geen
crashconsistentie- of cross-host-test, geen bewijs van productiegeschiktheid,
en geen autorisatie. De fixture bevat uitsluitend synthetische gegevens,
de verstrekte testreceipts zijn niet rechtsgeldig en alle verdicts houden
`decision: HOLD`, `authorization: DENY` en
`production_database_touched: false`. Een backendimplementatie vereist
een aparte beveiligingsreview en formele releaseprocedure.

## V11 — PostgreSQL-testcontract met geïsoleerde CI-database

De SQL-testfixture `tests/go20_postgres_contract.sql` is **geen
productiemigratie**. Ze maakt uitsluitend een `go20_test`-schema in
de tijdelijke PostgreSQL-service van een afzonderlijke GitHub Actions-job.
De fixture bevat geen `SECURITY DEFINER`, geen privilege-`GRANT`,
geen verbinding met PALACO MONO en geen deploymentstap.

De PL/pgSQL-testfunctie `go20_test.try_consume(...)` gebruikt
`SELECT ... FOR UPDATE` om concurrerende wijzigingen aan één toestand
te serialiseren. De transactie bewaakt zowel het revisienummer als de
verwachte toestandhash. Een unieke sleutel op de ontvangsthash weigert
hergebruik. Staatwijziging en ontvangstregistratie vinden in dezelfde
database-transactie plaats.

`tests/go20_postgres_contract_assertions.sql` controleert geldige
overgangen, verouderde revisies, onjuiste toestandhashes, ongeldig
bewijs, rollback bij een geïnjecteerde uitzondering en een retry
na rollback. `tests/run_go20_postgres_disposable.sh` doet daarnaast
twee concurrerende schrijfpogingen vanaf dezelfde oorspronkelijke revisie;
precies één mag slagen in de **testdatabase**.

De runner dwingt `PGHOST=127.0.0.1`, de synthetische testcredentials
en de opt-in CI-vlag af. Gebruik uitsluitend de speciaal aangemaakte
tijdelijke PostgreSQL-service. De runner is niet bedoeld voor lokale
of gedeelde databases.

**Beperkingen:** de code implementeert geen echte
PALACO MONO/Supabase-schema's, RLS, authenticatie of operationele
rollen. `TEST_ONLY_COMMIT` betekent uitsluitend dat de tijdelijke
PostgreSQL-testtransactie is uitgevoerd. PostgreSQL-gedrag buiten deze
specifieke transactie is niet bewezen. GO-13 blijft HOLD, autorisatie
DENY en geen enkele code uit deze testfixture mag zonder aparte review
naar productie worden gemigreerd.

## V12 — PostgreSQL-permissiegrenzen en negatieve RLS-tests

Deze kandidaat bevat twee nieuwe, uitsluitend voor de tijdelijke CI-database
bestemde testbestanden:
`tests/go20_postgres_rls_fixture.sql` en
`tests/run_go20_postgres_rls_disposable.sh`.

De SQL-fixture maakt twee synthetische `NOLOGIN`-rollen, `go20_alpha` en
`go20_beta`. Beide krijgen uitsluitend `USAGE` op het test-schema en
`SELECT` op de afzonderlijke `tenant_evidence`-tabel. Deze tabel heeft
`ENABLE ROW LEVEL SECURITY` én `FORCE ROW LEVEL SECURITY`. Een
`FOR SELECT`-policy vergelijkt `tenant_role` met `CURRENT_USER`.
De roles kunnen daardoor uitsluitend hun eigen testbewijs zien.

De testen controleren dat gebruikers **geen** directe `SELECT` op de
interne replaytoestand of ontvangsttabel hebben, geen `INSERT` of
`UPDATE` op de tenanttabel mogen uitvoeren en de replay-RPC
`go20_test.try_consume` niet mogen aanroepen. De standaard
`PUBLIC EXECUTE`-toestemming wordt op die testfunctie ingetrokken.

De GitHub Actions PostgreSQL-testservice gebruikt nu de reeds door de
GO-16-provenance-policy vastgelegde PostgreSQL 17-container met een
immutabele SHA-256-image-digest. Dit herstelt de eerder geconstateerde
niet-vastgepinde containerreferentie; formele CI-verificatie blijft vereist.

**Grenzen:** de tests gebruiken `SET ROLE` binnen een lokale,
wegwerpbare database met synthetische rollen. De werkelijke PALACO MONO
rolstructuur, authenticatie en PostgreSQL/Supabase RLS-regels zijn niet
gewijzigd of gevalideerd. Een administratieve eigenaar of superuser
behoudt zijn eigen beheermogelijkheden; deze test doet geen uitspraken
over veiligheid onder een gecompromitteerd databasebeheeraccount.
Testsucces geeft nooit autorisatie: GO-13 blijft **HOLD / DENY**.

## V13 — synthetische principalbinding en multi-tenant-negatieve tests

`tests/go20_postgres_identity_fixture.sql` en
`tests/run_go20_postgres_identity_disposable.sh` bouwen voort op de v12
tijdelijke PostgreSQL-testdatabase. Een extra tabel koppelt twee synthetische
identiteiten aan hun eigen database-rol. De RLS-policy gebruikt uitsluitend
`CURRENT_USER` voor de tenantbinding. De tests loggen voor de
negatieve controles uitdrukkelijk als laagbevoegde principals in via
`SET SESSION AUTHORIZATION`, zodat privilege-escalatie met
`SET ROLE` naar de andere testrol daadwerkelijk wordt geweigerd.

De regressiecontrole bewijst binnen de testfixture dat:
- iedere principal maar één eigen identiteitsrecord ziet;
- een vervalste, door de client instelbare sessievariabele de RLS-policy
  niet verandert;
- laagbevoegde principals geen `SET ROLE` naar de andere tenant mogen
  uitvoeren;
- identiteitsrecords niet kunnen worden geschreven en interne
  replaytabellen en de replayfunctie afgeschermd blijven.

Tevens is de foutieve v12-testaanname hersteld die na een voorgaande
geslaagde v11-test ten onrechte nul ontvangstrecords verwachtte.
De v12-test verifieert nu dat het bestaande aantal ontvangstrecords
**ongewijzigd blijft** tijdens negatieve autorisatiecontroles.

**Geen productiekoppeling:** echte PALACO ONE-accounts, Supabase JWT's,
RLS-identiteitclaims, database-rollen en live services zijn niet
aangesloten. Het testmodel gebruikt opzettelijk echte PostgreSQL-rollen
in een wegwerpdatabase, geen onbewezen clientclaims. Deze geslaagde
testvoorwaarden verlenen geen productiebevoegdheid; GO-13 blijft HOLD
en autorisatie DENY.

## V14 — cross-tenant-aanvalstests en transactionele auditregistratie

`tests/go20_postgres_audit_fixture.sql` voegt **uitsluitend in de tijdelijke
PostgreSQL CI-database** de tabel `go20_test.audit_events` toe. Een
`AFTER INSERT OR UPDATE OR DELETE`-trigger registreert geslaagde
wijzigingen aan `tenant_evidence`, inclusief operatietype, uitvoerende
database-rol, synthetische tenant en bewijs-hash. Een afzonderlijke
trigger weigert gewone `UPDATE`- en `DELETE`-pogingen op auditregels.
Beide laagbevoegde tenantrollen hebben geen rechten op de audittabel.

`tests/run_go20_postgres_audit_disposable.sh` toetst:

- Cross-tenant selectie met expliciete filters en joins levert geen
  records van de andere synthetische tenant op.
- Vervalste clientinstelbare identiteitsclaims veranderen de RLS-binding
  aan `CURRENT_USER` niet.
- Onbevoegde rolwisselingen, uitschakelpogingen van RLS, schrijfpogingen
  en toegang tot audit/replaytabellen worden geweigerd.
- Geweigerde pogingen veranderen de uitgangstoestand niet.
- Een geslaagde **test-only** wijziging genereert precies één auditregel.
- Een `ROLLBACK` verwijdert zowel de testwijziging als de auditregel.
- Een gewone `DELETE` op de audittabel wordt door de beschermende
  trigger geweigerd.

**Auditgrens:** dit is een transactionele DML-audit van een synthetische
tabel; geweigerde SQL-aanroepen worden niet als auditregel opgeslagen.
De audit is evenmin een extern of cryptografisch onveranderlijk logboek:
een databasebeheerder met superuser-/DDL-macht kan triggers en tabellen
wijzigen. De tests bewijzen geen productie-auditdekking, externe
retentie, vertrouwde identiteit, ketenverificatie of PostgreSQL-hardening.
De gehele fixture is voor geïsoleerde CI bedoeld en mag niet zonder
aparte review in PALACO MONO worden toegepast. **GO-13 HOLD / DENY.**

## V15 — onafhankelijke audit-exportcontrole en foutinjectie

`scripts/pr_audit_integrity.py` verifieert een offline JSON-auditexport
tegen een **extern en onafhankelijk aangeleverd** SHA-256-ankerpunt:

```sh
python3 scripts/pr_audit_integrity.py audit-export.json \
  --expected-head-sha256 <64-hex-anker>
python3 -m unittest discover -s tests -p 'test_pr_audit_integrity.py' -v
```

De export gebruikt `schema: palaco.go20-audit-export.v1` en
`events` (maximaal 10.000). Elk record bevat `id` (oplopend
vanaf 1), `operation`, `actor_role`, `tenant_role`,
`entry_sha256`, `previous_sha256` en `event_sha256`.
`event_sha256` is de SHA-256 van canonieke JSON van het record zonder
die eigen hash. Het eerste `previous_sha256` is 64 nullen;
vervolgrecords verwijzen naar de vorige `event_sha256`.
Verwijdering, herschikking, manipulatie en een afwijkend eindanker
leiden tot een afwijzing. De externe ankerwaarde mag **niet**
uit dezelfde onbewezen auditexport worden overgenomen.

**Belangrijk:** de bestaande PostgreSQL-test-audittabel v14 heeft
geen ingebouwde hashketen. De verifier controleert een afzonderlijk
opgebouwde JSON-export; hij leest niet rechtstreeks uit PALACO MONO en
claimt geen onafhankelijke attestatie of geauthenticeerde
exportvoorziening. De provenance, publicatie, authenticiteit en
actualiteit van het externe anker vereisen afzonderlijk ontwerp
en autorisatie. Hashes bieden integriteitscontrole bij een betrouwbaar
extern anker, maar geen op zichzelf staande onveranderlijkheid.

`tests/go20_postgres_audit_faults.sql` controleert in de wegwerpbare
CI-PostgreSQL-service dat geïnjecteerde uitzonderingen na een
geauditeerde invoeging zowel data als auditregel terugdraaien,
ongeldige invoer geen auditregel produceert en gewone
verwijdering van auditregels wordt geweigerd.

### Acceptatiecriteria voor de kandidaat

1. Alle GO-20 Python-regressies, waaronder de tien
   nieuwe auditintegriteitsgevallen, slagen.
2. De geïsoleerde PostgreSQL-job slaagt, inclusief tenant-RLS,
   replay- en auditfoutinjectiecontroles.
3. De bestaande repository-brede security-, supply-chain-,
   SBOM- en governancechecks slagen.
4. Het testarchief bevat geen productiemigraties en verandert
   geen externe of PALACO MONO-database.
5. Ook als alle technische criteria slagen blijven PR #109
   **Draft**, GO-13 **HOLD** en autorisatie **DENY**;
   een afzonderlijke menselijke vrijgave zou vereist zijn.

Dit document en de implementatie geven geen automatische
acceptatie, merge-, publicatie- of uitvoeringsrechten.

## V16 — gecontroleerde exportbrug naar offline auditverificatie

De afzonderlijke, fail-closed \`scripts/pr_audit_export.py\` converteert
newline-delimited JSON-bronregels uit een lokaal aangeleverd bestand naar
de v15-auditexport (\`palaco.go20-audit-export.v1\`). De bron moet een
strikt oplopende, positieve PostgreSQL-\`id\` bevatten. **Gaten** zijn
toegestaan: PostgreSQL-sequences worden niet teruggedraaid bij ROLLBACK.
De export kent aaneengesloten ketenposities \`1..N\` toe en bewaart de
werkelijke database-ID's afzonderlijk in het manifest
(\`palaco.go20-export-manifest.v1\`). Per record worden de vorige
eventhash en de SHA-256 van canonieke JSON vastgelegd. De converter
weigert ongeldige, dubbele of ongeordende bronsleutels, onverwachte
velden, te grote invoer en bestaande uitvoerbestanden.

\`\`\`sh
python3 scripts/pr_audit_export.py \
  --input-ndjson audit-source.ndjson \
  --output-export audit-export.json \
  --output-manifest audit-manifest.json
python3 scripts/pr_audit_integrity.py audit-export.json \
  --expected-head-sha256 <INDEPENDENT_VASTGELEGD_SHA256_ANKER>
python3 -m unittest discover -s tests -p 'test_pr_audit_export.py' -v
\`\`\`

In \`tests/run_go20_audit_export_disposable.sh\` worden auditrecords via
\`row_to_json\` uit de wegwerpbare PostgreSQL CI-database opgehaald,
geëxporteerd, tegen het lokaal berekende testanker gecontroleerd en
vervolgens bewust gemanipuleerd. De gemanipuleerde export **moet**
worden afgewezen met behoud van \`HOLD / DENY\`.

**Bewijsgrens:** het manifest is afkomstig uit dezelfde bron als de
export, is niet digitaal ondertekend en vormt dus **geen onafhankelijk
bewijsanker**. Het testanker wordt alleen vastgezet vóór de testmutatie;
een kwaadwillende met controle over zowel bron als anker kan beide
herberekenen. Een echt onafhankelijk attestatieproces vereist een apart
geauthenticeerde, onveranderbare opslag van de ankerwaarde inclusief
tijdstip, bronidentiteit, volledigheidscontrole en formele sleutel-/rol-
governance. Noch die opslag noch een productieverbinding is in v16
geïmplementeerd. De auditbron is uitsluitend de synthetische
\`go20_test.audit_events\`-tabel; PALACO MONO blijft ongewijzigd.
GO-13 blijft **HOLD**, autorisatie **DENY**, PR #109 blijft **Draft**.

## V17 — extern ondertekend auditcheckpoint, intrekking en volledigheidsbinding

`scripts/pr_signed_audit_checkpoint.py` bevat een afzonderlijke,
alleen-lezen verifier voor de auditexport van v16. De verifier vereist
**vier onafhankelijke invoeren**: auditexport, v16-manifest, ondertekend
checkpoint en een afzonderlijk beheerd vertrouwd-sleutelregister.
Daarbovenop moet de controleur een **minimumrevisie** aanleveren
die niet uit het te verifiëren checkpoint is overgenomen.

```sh
python3 scripts/pr_signed_audit_checkpoint.py \
  --export audit-export.json \
  --manifest audit-manifest.json \
  --checkpoint externally-signed-checkpoint.json \
  --trusted-keys trusted-audit-keys.json \
  --minimum-revision 7
python3 -m unittest discover -s tests -p 'test_pr_signed_audit_checkpoint.py' -v
```

Het externe register gebruikt het schema `palaco.go20-audit-trust.v1`
met `keys`: iedere sleutel heeft `public_key_hex` (32 bytes, als
64 kleine hextekens) en `status` (`active` of `revoked`).
Een ingetrokken sleutel geeft altijd een afwijzing, ook als haar
handtekening cryptografisch geldig is. De verifier weigert
een ontbrekend, onjuist of onbekend register.

Het checkpoint heeft `payload`, `signer_key_id` en
`signature_ed25519_hex`. De payload gebruikt het schema
`palaco.go20-signed-audit-checkpoint.v1` met:
`revision`, `repository`, `export_sha256`,
`head_sha256`, `event_count`, `source_ids_sha256`,
`first_source_id` en `last_source_id`.
De repository moet exact `Maurits-pixe/PALACO` zijn.
De Ed25519-handtekening geldt voor de **ruwe 32 SHA-256-bytes**
van de gecanoniseerde statement met
`schema: palaco.go20-audit-checkpoint-signature.v1` en
`payload_sha256` van de volledige checkpoint-payload.

**Volledigheidscontrole binnen de ondertekende momentopname:** de
verifier toetst het aantal events, de JSON-exporthash, de
eindketenhash, de hash van alle afzonderlijke en strikt oplopende
PostgreSQL-bron-ID's, de eerste en laatste bron-ID en de
extern verwachte minimumrevisie. Zowel de bron-ID-lijst als
de export moeten met het ondertekende checkpoint overeenstemmen.
Een ontbrekende, vervalste of herschikte gebeurtenis resulteert
in `checkpoint_valid: false`.

**Beperkingen:** dit bewijst de consistentie van de aangeleverde
checkpointset, **niet** dat een kwaadwillende databasebeheerder
nooit records heeft achtergehouden vóór ondertekening. Het register,
de actuele intrekkingsstatus en de minimale revisie moeten via
een onafhankelijke, geauthenticeerde beheerstroom worden verkregen;
de lokale CLI haalt die niet automatisch op. Er is geen
sleuteluitgifte, signing-service, extern grootboek, tijdsattest,
rollbackbestendige centrale opslag of live databasekoppeling.
De positieve Ed25519-regressietest vereist de optionele
`cryptography`-bibliotheek; zonder deze bibliotheek weigert de
verifier verificatie en kan de positieve integratietest worden
overgeslagen. Alle uitkomsten blijven `decision: HOLD` en
`authorization: DENY`. **GO-13 HOLD, PR #109 Draft.**

## V18 — historische auditcheckpoint-continuïteit en externe witness

`scripts/pr_audit_continuity.py` vergelijkt twee **volledig cumulatieve**
v17-checkpointbundels en verifieert beiden met het afzonderlijk
aangeleverde vertrouwde sleutelregister. Iedere bundel heeft exact
`export`, `manifest` en `checkpoint`. Een vierde input,
`palaco.go20-audit-prior-witness.v1`, bevat de eerder onafhankelijk
vastgelegde `revision` en `checkpoint_payload_sha256`.
Deze witness moet uit een vertrouwde bron komen en mag niet
door de huidige auditexport zelf worden bepaald.

```sh
python3 scripts/pr_audit_continuity.py \
  --previous-bundle previous.json \
  --current-bundle current.json \
  --trusted-keys trusted-audit-keys.json \
  --independent-witness prior-witness.json
python3 -m unittest discover -s tests -p 'test_pr_audit_continuity.py' -v
```

De verifier vereist dat beide Ed25519-checkpoints voldoen aan v17,
de vorige checkpoint-payload exact overeenkomt met de onafhankelijke
witness, de nieuwe revisie **precies één** groter is, en het cumulatieve
eventaantal toeneemt. De volledige historische eventreeks en de
oorspronkelijke PostgreSQL-bron-ID's moeten een **ongewijzigde prefix**
van de nieuwe reeks zijn. Nieuwe records mogen de oude reeks uitsluitend
aan het einde verlengen. De repositorybinding, hashes, sleutelstatus,
aanwezige events en bron-ID-grenzen blijven ondertekend geverifieerd.

Negatieve regressies omvatten historische recordverwijdering,
recordvervanging, verandering van oude bron-ID's, onjuiste witnesses,
revisiesprongen, herhaalde checkpoints, ingetrokken sleutels,
handtekeningmanipulatie en repositorysubstitutie.

**Grenzen:** de onafhankelijke witness wordt in v18 **niet**
gepubliceerd, ondertekend, opgeslagen of opgehaald; een eerder
betrouwbaar bewaard exemplaar is verplicht. Deze offline verifier
bewijst slechts dat de twee aangeleverde, ondertekende momentopnames
binnen deze contractvorm een append-only historische relatie hebben.
Eventverlies vóór het eerste vertrouwde checkpoint, gelijktijdige
uitgifte van conflicterende checkpoints, sleutelcompromittering,
vertraging en onvolledige bronregistratie kunnen hiermee niet worden
uitgesloten. De positieve cryptografische tests vereisen de optionele
`cryptography`-backend; anders worden zij overgeslagen en kan
de verifier niet positief valideren. Alle verdicts blijven
`decision: HOLD` en `authorization: DENY`.
GO-13 blijft HOLD, PR #109 Draft, zonder productieaanpassingen.

## V19 — afzonderlijk ondertekende getuigen en audit-forkdetectie

`scripts/pr_audit_witness_forks.py` controleert in alleen-lezen modus
of onafhankelijke, Ed25519-ondertekende getuigenverklaringen elkaar
tegenspreken over **dezelfde** auditcheckpointrevisie.

```sh
python3 scripts/pr_audit_witness_forks.py \
  --evidence witnessed-bundles.json \
  --audit-trust independently-pinned-audit-keys.json \
  --witness-trust independently-pinned-witness-keys.json \
  --expected-revision 42 \
  --minimum-witnesses 2
python3 -m unittest discover -s tests -p 'test_pr_audit_witness_forks.py' -v
```

De `evidence`-input gebruikt `schema:
palaco.go20-witness-evidence.v1` en twee arrays:
`bundles` (1–16 v17-bundels met export, manifest, checkpoint) en
`attestations` (1–64 onafhankelijke verklaringen). De bundels
worden eerst integraal via de v17-checkpointverifier en het externe
auditsleutelregister gecontroleerd. De verwachte revisie is expliciet
en **mag niet** uitsluitend uit een onbetrouwbare bundel komen.

Het tweede, afzonderlijke getuigensleutelregister
(`palaco.go20-witness-trust.v1`) houdt per `witness_id` een
Ed25519-`public_key_hex` en `active`/`revoked`-status bij.
Getuigen ondertekenen de canonieke statement
`palaco.go20-witness-statement.v1`, met `witness_id`,
`revision` en `checkpoint_payload_sha256`.
De Ed25519-verificatie wordt domeingescheiden uitgevoerd volgens
de bestaande PALACO-handtekeningconventie.

De controle weigert onbekende, ingetrokken, dubbele en vervalste
getuigenverklaringen, niet-ondertekende of ongeldige auditbundels,
ongeldige revisies en onvolledige getuigenquorums. Het quorum vereist
standaard **twee verschillende actieve getuigensleutels** per
gecontroleerde checkpoint, configureerbaar van twee tot acht.
Wanneer twee verschillende, cryptografisch geverifieerde
checkpoint-payloads van dezelfde revisie getuigenverklaringen hebben,
rapporteert de tool `fork_detected: true` en
`signed_checkpoint_fork_detected`. Een getuige die twee afwijkende
hashes ondertekent, wordt apart als `witness_equivocation` gemarkeerd.
**Geen enkel geldig quorum geeft toestemming tot vrijgave of
uitvoering:** alle antwoorden behouden `decision: HOLD` en
`authorization: DENY`.

**Grenzen:** deze tool is geen publicatie-, quorum- of sleutelbeheer-
dienst. Onafhankelijkheid van de sleutels is een externe organisatorische
voorwaarde; verschillende sleutel-ID's bewijzen op zichzelf geen
onafhankelijke eigenaarschap of fysieke gescheiden opslag. Verbergde
checkpoints zonder aangeboden getuigenverklaringen zijn hiermee niet
detecteerbaar. Voor detectie van split views op verschillende momenten
zijn transparante, duurzame getuigenregisters, authenticatie van
publieke sleutelwijzigingen en gossip tussen onafhankelijke
waarnemers nodig. Er is geen dergelijke dienst, databasewijziging,
signing-service of productieautorisatie gebouwd. De positieve
Ed25519-regressies vereisen de optionele `cryptography`-backend;
zonder backend worden die tests overgeslagen, en verificatie weigert
de technische acceptatie. **GO-13 HOLD / DENY; PR #109 Draft.**

## V20 — transparante offline getuigenlogs en conflicterende publicaties

De module \`scripts/pr_witness_transparency.py\` controleert een
**afzonderlijk aangeleverd**, offline journal van per-getuige
ondertekende checkpointpublicaties. Er is geen webservice, geen
automatische publicatie, geen database en geen productie-integratie.

\`\`\`sh
python3 scripts/pr_witness_transparency.py \
  --logbook witness-transparency.json \
  --witness-trust trusted-witness-keys.json \
  --independent-pins externally-retained-heads.json \
  --start-revision 21
python3 -m unittest discover -s tests \
  -p 'test_pr_witness_transparency.py' -v
\`\`\`

Het journal gebruikt \`schema: palaco.go20-witness-transparency.v1\`,
met twee tot zestien getuigenlogs. Elke getuige heeft een \`witness_id\`
en één tot 256 cumulatief opeenvolgende publicaties:
\`sequence\`, \`revision\`, \`checkpoint_payload_sha256\`,
\`previous_entry_sha256\`, \`entry_sha256\` en
\`signature_ed25519_hex\`. De statement heeft het schema
\`palaco.go20-transparency-entry.v1\` en wordt per entry met
Ed25519 ondertekend volgens de bestaande PALACO-domeinscheiding.
De genesis-voorganger bestaat uit 64 hexnullen. De
\`entry_sha256\` is SHA-256 van het canonieke statement.

De controle vereist afzonderlijk aangeleverde actieve
getuigensleutels (\`palaco.go20-witness-trust.v1\`) en een eerder
**onafhankelijk vastgelegde** verzameling logkoppen
(\`palaco.go20-transparency-pins.v1\`), met voor iedere getuige
\`last_sequence\` en \`head_sha256\`. De extern vastgelegde
\`start_revision\` moet voor beide logs gelijk zijn; publicaties
dienen per getuige zonder ontbrekende revisies of posities te volgen.
De controle weigert afwijkende logkoppen, ongeldige
handtekeningen, ontbrekende regels, verkorte geschiedenis,
dubbele getuigenidentiteiten, ingetrokken sleutels en niet-overeenkomende
publicatiehorizonnen. Twee geldige, onafhankelijke getuigenlogs
die over dezelfde revisie verschillende checkpointpayloadhashes
publiceren, veroorzaken \`fork_detected: true\` en
\`conflicting_signed_publications\`.

**Geen volledig transparant publicatiesysteem:** deze code verifieert
uitsluitend **aangeleverde** logboeken. Ze schrijft of verspreidt
geen publicaties en beheert geen onafhankelijke, duurzame
getuigenopslag. De externe pinnen mogen niet uitsluitend uit
de aangeleverde logs worden herberekend. Meerdere sleutels
bewijzen niet dat hun eigenaars onafhankelijk zijn. Deze
logcontrole verifieert de publicatieverklaring, maar vereist
een separate v17-verificatie van de bijbehorende auditcheckpointbundels
en v18-continuïteit voordat de onderliggende auditevents zelf
cryptografisch zijn geverifieerd. Een niet-gepubliceerde fork
kan niet worden gedetecteerd. Alle verdicts blijven
\`decision: HOLD\` en \`authorization: DENY\`;
PR #109 blijft Draft, GO-13 blijft HOLD.

## V21 — geïntegreerde multi-round auditbeoordeling en anti-rollback

De alleen-lezen `scripts/pr_multiround_assessor.py` verenigt de
technische controles uit v17–v20 tot één fail-closed beoordeling van
**2 tot 16 opeenvolgende, cumulatieve auditcheckpoints**.

```sh
python3 scripts/pr_multiround_assessor.py \
  --roundbook rounds.json \
  --audit-trust trusted-audit-keys.json \
  --witness-trust trusted-witness-keys.json \
  --transparency-logbook signed-witness-logs.json \
  --independent-pins independently-retained-log-heads.json \
  --independent-baseline independently-retained-round-anchors.json
python3 -m unittest discover -s tests -p 'test_pr_multiround_assessor.py' -v
```

Het roundbook gebruikt schema `palaco.go20-multiround-evidence.v1`
met een array `rounds`: iedere ronde bevat `export`,
`manifest` en `checkpoint`. De extern vastgelegde baseline
(`palaco.go20-multiround-baseline.v1`) bevat
`first_revision`, `first_payload_sha256`, `last_revision`
en `last_payload_sha256`. Beide grenzen zijn verplicht,
mogen niet uitsluitend uit het roundbook worden afgeleid en
moeten overeenkomen met de ondertekende eerste en laatste
auditcheckpointpayload.

De beoordeling controleert per ronde de v17-handtekening,
sleutelintrekking en bron-ID-volledigheid; tussen iedere twee
rondes de v18-historische prefix en exact één revisiestap;
en over de hele reeks de v20-Ed25519-publicaties en onafhankelijke
pinnen van iedere getuige. Iedere getuige moet voor **iedere**
aangeleverde ronde precies de juiste payloadhash hebben
gepubliceerd. Een ontbrekende ronde, historische mutatie, ingetrokken
sleutel, revisieterugval, ontbrekende publicatie of gesplitste
getuigenweergave geeft een negatieve technische beoordeling.

De JSON-uitkomst `palaco.go20-multiround-assessment.v1` bevat
`technical_evidence_valid`, `rounds_checked`, afzonderlijke
`checks` en foutcodes. Ook bij `technical_evidence_valid: true`
blijven `decision: HOLD`, `authorization: DENY` en
`production_commit_performed: false`.

**Vertrouwensgrenzen:** de eerste en laatste checkpointankers én
de afzonderlijke ondertekende getuigenlogkoppen moeten vooraf via
een **onafhankelijk, geauthenticeerd kanaal** worden vastgelegd;
de module beheert dat kanaal niet. Tussenliggende
witness-referenties worden tijdens de verificatie afgeleid
uit reeds cryptografisch geverifieerde checkpoints en zijn
geen externe attestaties. De module verzamelt geen onbekende
publicaties, controleert geen klok-/timestampbewijs en
bewijst geen bronvolledigheid vóór het eerste anker. Er is geen
uitvoering, merge, uitrol, signing-service of verbinding met
PALACO MONO. GO-13 blijft HOLD; PR #109 blijft Draft.

## V22 — reproduceerbare beoordelingsreceipt en onafhankelijke hercontrole

De alleen-lezen module `scripts/pr_assessment_receipt.py` legt de
v21-technische beoordeling vast in een deterministisch JSON-document,
`palaco.go20-assessment-receipt.v1`. De invoer is een lokaal JSON-object
met **zes verplichte onderdelen**: `roundbook`, `audit_trust`,
`witness_trust`, `logbook`, `external_pins` en `baseline`.
Een ontbrekend of extra onderdeel wordt afgewezen.

```sh
python3 scripts/pr_assessment_receipt.py --inputs independently-provided-evidence.json
python3 scripts/pr_assessment_receipt.py \
  --inputs independently-provided-evidence.json \
  --verify-receipt previously-recorded-receipt.json
python3 -m unittest discover -s tests -p 'test_pr_assessment_receipt.py' -v
```

Bij het opbouwen wordt de bestaande v21-beoordelaar opnieuw uitgevoerd,
zonder externe systemen te wijzigen. Het resultaat omvat de volledige
`assessment`, een SHA-256 van de zes invoeronderdelen samen, afzonderlijke
componenthashes en de hash van het uiteindelijke receipt-document.
De receipt bevat expliciet `independently_attested: false`.

**Verificatie is niet alleen een hashvergelijking.** De verifier
herberekent de volledige v21-beoordeling uit de apart aangeleverde
bronbestanden, inclusief alle ondertekende auditmomentopnames, historische
continuïteit en getuigenlogs. Hij vergelijkt daarna de originele receipt
met de opnieuw berekende componenthashes, status, foutcodes, controles
en receipt-hash. Vervalste autorisatie, gewijzigde PASS-status,
ontbrekende bewijsdelen, ingetrokken getuigensleutels en ontbrekende
historische rondes veroorzaken een negatieve beoordeling. Ongeldige
JSON, dubbele JSON-sleutels, te grote invoer en onjuiste nested
objectstructuren worden fail-closed behandeld. Negatieve invoertests
zijn onderdeel van de GitHub Actions-workflow.

**Vertrouwensgrens:** de receipt is niet digitaal ondertekend, is geen
onafhankelijk bewijsanker, en bewaart zelf geen externe oorsprong.
Voor een reproduceerbare controle dienen dezelfde originele zes
evidencebronnen via een afzonderlijk betrouwbaar kanaal beschikbaar te
zijn. De module doet geen productieoperaties en verleent ook bij
`receipt_valid: true` geen autorisatie: `decision: HOLD`,
`authorization: DENY` en `external_attestation_verified: false`.
GO-13 HOLD; PR #109 Draft, zonder merge of uitrol.
