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

## V23 — ondertekende review, rolscheiding en definitieve HOLD-gate

`scripts/pr_signed_assessment_review.py` is een alleen-lezen
Ed25519-verifier voor het **opnieuw berekende** v22-bewijsrapport.
De verifier accepteert een afzonderlijk ondertekende
`palaco.go20-signed-assessment-review.v1`-envelop met precies twee
attestaties, plus een extern aangeleverd
`palaco.go20-reviewer-role-trust.v1`-register.

```sh
python3 scripts/pr_signed_assessment_review.py \
  --review signed-review.json \
  --receipt receipt.json \
  --inputs independently-provided-evidence.json \
  --reviewer-trust independently-provisioned-reviewer-keys.json
python3 -m unittest discover -s tests \
  -p 'test_pr_signed_assessment_review.py' -v
```

Iedere attestatie bevat `role`, `reviewer_id` en
`signature_ed25519_hex`. De verplichte, **verschillende rollen**
zijn `evidence_reviewer` en `security_reviewer`. Het externe
register koppelt elke reviewer-ID aan `public_key_hex`,
`status: active|revoked` en precies één toegewezen rol.
Dubbele reviewer-ID's, hetzelfde publieke sleutelmateriaal in
beide rollen, rolverwisseling, ongeldige handtekeningen en
ingetrokken sleutels worden geweigerd. De Ed25519-handtekening
beschermt een domeingescheiden statement
`palaco.go20-reviewer-attestation.v1` met repository,
receipt-hash, reviewer-ID, rol en expliciete HOLD/DENY-status.

De verifier vergelijkt de envelope met de SHA-256 van de
oorspronkelijke receipt, voert de **volledige v22-herberekening**
uit aan de hand van zes onafhankelijk aangeleverde bewijsbronnen
en eist een positief technisch resultaat vóór de review
`review_valid: true` kan zijn. Een ondertekend verslag betekent
**uitsluitend review-integriteit**, geen bevoegdheid tot vrijgave.
Zelfs twee geldige reviewers geven nooit `ALLOW`: iedere
uitkomst behoudt `decision: HOLD`, `authorization: DENY`,
`release_authorized: false` en `production_commit_performed: false`.

**Grenzen:** reviewerrollen, sleutelbeheer en actueel intrekkingsbeleid
moeten buiten deze offline module onafhankelijk en betrouwbaar worden
beheerd. Twee sleutels bewijzen geen daadwerkelijke organisatorische
onafhankelijkheid. Er is geen automatische signer, reviewerapp,
rollentoewijzing, PR-approval, merge, webhook, autorisatiegate
voor productie of databasewijziging geïmplementeerd.
De positieve Ed25519-test vereist `cryptography`; zonder de backend
wordt de test overgeslagen en weigert de verifier positieve
verificatie. PR #109 blijft Draft en GO-13 blijft HOLD.

## V24 — reviewer-governance, conflicterende belangen en vrijgaveverbod

`scripts/pr_review_governance.py` voegt aan de v23-ondertekende
review een onafhankelijk aangeleverd governancebeleid toe.
Het beleid (`palaco.go20-reviewer-governance.v1`) bevat een
revisie, repositorybinding, een rooster voor de rollen
`evidence_reviewer` en `security_reviewer`, de expliciet
verboden capabilities en opgegeven belangenconflicten.

```sh
python3 scripts/pr_review_governance.py \
  --review signed-review.json \
  --receipt receipt.json \
  --inputs independent-evidence.json \
  --reviewer-trust independent-reviewer-keys.json \
  --policy governance-policy.json \
  --independent-policy-pin independent-governance-pin.json
python3 -m unittest discover -s tests -p 'test_pr_review_governance.py' -v
```

Een afzonderlijk bewaarde policy-pin
(`palaco.go20-governance-policy-pin.v1`) bevat
`minimum_revision` en `policy_sha256`. De controle
weigert elke beleidsrollback, hashafwijking en
repositorymismatch. Per reviewer vereist het rooster
`reviewer_id`, `organization_id`, `control_domain_id`,
`conflict_disclosed: false` en `governance_status: active`.
De twee rollen moeten verschillende reviewer-ID's,
organisatie-ID's en sleutelbeheerdomeinen hebben.
De roosteridentiteiten worden vergeleken met de twee
cryptografisch geverifieerde v23-reviewattestaties.

Het beleid vereist exact deze zes verboden capabilities:
`release`, `merge`, `deploy`, `production_write`,
`policy_override` en `self_approval`. Ontbrekende,
dubbele of afwijkende capabilities worden geweigerd.
Een niet-lege lijst `declared_conflicts`, een opgegeven
reviewerconflict of een inactieve reviewer maakt de
governancecontrole ongeldig. Ongeacht de technische
geldigheid blijven de outputs `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`, `deployment_authorized: false`
en `production_commit_performed: false`.

**Grenzen:** dit detecteert alleen conflicten die uit het
aangeleverde, onafhankelijk geankerde beleid blijken.
Twee verschillende organisatie-ID's of key domains
bewijzen geen daadwerkelijke organisatorische onafhankelijkheid,
goede intenties of afwezigheid van samenspanning. Een
onbetrouwbare partij die zowel beleid als zogenaamd
onafhankelijke pin kan wijzigen, kan de gegevens vervalsen.
Er is geen echte HR-verificatie, externe identiteitscontrole,
beheerservice, productieautorisatie of GitHub-mergepoort
geïmplementeerd. GO-13 blijft HOLD; PR #109 blijft Draft.

## V25 — doorlopende governancegeschiedenis en gecontroleerde reviewerrotatie

`scripts/pr_governance_history.py` verifieert in alleen-lezen
modus een keten van 2–16 opeenvolgende v24-governanceversies met
verplicht ondertekende overgangsverklaringen.

```sh
python3 scripts/pr_governance_history.py \
  --history governance-history.json \
  --independent-pin independently-retained-governance-history-pin.json \
  --controller-trust independently-provisioned-governance-controllers.json
python3 -m unittest discover -s tests -p 'test_pr_governance_history.py' -v
```

Het historydocument (`palaco.go20-governance-history.v1`)
bevat `snapshots` en `transitions`. Iedere snapshot draagt
de bijbehorende `policy`, cryptografische `review`,
`receipt`, de zes originele `inputs` en `reviewer_trust`.
**Iedere snapshot** wordt met de volledige v24-module opnieuw
gevalideerd, inclusief de geverifieerde v23-handtekeningen,
v22-rapportherberekening en de oorspronkelijke v21-evidence.
De governanceversies moeten zonder revisiesprong oplopen.

Een afzonderlijke, extern vastgelegde pin
(`palaco.go20-governance-history-pin.v1`) verankert de
eerste en laatste beleidsversies met hun SHA-256-hashes
en exacte revisies. Iedere overgang bevat oude en nieuwe
revisie en beleidshash, een lijst `changed_roles`, de
`controller_id` en diens Ed25519-handtekening over een
domeingescheiden `palaco.go20-governance-transition.v1`
statement. De publieke sleutel van de controller wordt
gecontroleerd tegen een **apart** aangeleverd, actueel
`palaco.go20-governance-controller-trust.v1`-register.
Een ingetrokken controller of een controller met dezelfde
publieke sleutel als een reviewer wordt geweigerd.

Bij een reviewerrotatie mogen **maximaal één rol per
governanceovergang** en de bijbehorende revieweridentiteit
en sleutelregistratie wijzigen. Een onverklaarde wijziging,
dubbele rotatie, ongelijke overgangshashes, vervalste
handtekeningen, gewijzigde verboden capabilities of een
historisch ongeldige reviewerattestatie leidt tot afwijzing.

### Beveiligingsacceptatiecriteria

1. Alle v11–v25 PostgreSQL-, RLS-, replay-, audit- en Python-
   tests moeten zijn uitgevoerd; geen mislukte verplichte CI-jobs.
2. Iedere historische snapshot moet opnieuw cryptografisch
   en beleidsmatig geldig zijn, ook als de huidige snapshot
   geldig is.
3. Een externe governancecontroller is nodig om elke
   beleidsversieovergang te attesteren; diens sleutel
   moet van reviewers gescheiden zijn.
4. Historische begin- en eindankers, actuele reviewer- en
   controllerregisters mogen niet uitsluitend uit de
   te controleren geschiedenis zelf zijn overgenomen.
5. De PR blijft Draft en alle reviews blijven strikt
   adviserend: GO-13 HOLD, autorisatie DENY, geen merge
   en geen productie-uitrol.

**Grenzen:** handtekeningen bewijzen geen feitelijke
organisatorische onafhankelijkheid, noch de authenticiteit
van een extern aangeleverd sleutelregister. De module bewaart
geen ankers, beheert geen sleutels, roteert geen echte accounts
en wijzigt geen GitHub-governance. Ook een volledig positief
verdict behoudt `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false` en
`production_commit_performed: false`.

## V26 — fail-closed governancehardening en vijandige bewijsinvoer

`scripts/pr_governance_hardening.py` biedt een afzonderlijke, alleen-lezen
beveiligingslaag rond de historische v25-governanceverificatie.

```sh
python3 scripts/pr_governance_hardening.py \
  --history governance-history.json \
  --independent-pin externally-retained-history-pin.json \
  --controller-trust independently-provisioned-controller-keys.json
python3 -m unittest discover -s tests -p 'test_pr_governance_hardening.py' -v
```

De ingang accepteert uitsluitend afzonderlijk aangeleverde JSON-bestanden,
begrenst elk bronbestand op 8 MiB, JSON-diepte op 64 niveaus, de totale
nodeomvang op 250.000 en strings op maximaal 1.000.000 tekens.
Dubbele JSON-sleutels, niet-finite getallen en niet-canonieke in-memory
waardetypen worden geweigerd. Corruptie van historische snapshots,
trustregisters, reviewerattestaties, rolrotaties en ondertekende
overgangen wordt fail-closed verwerkt.

Bij technisch geldige input controleert v26 de **complete**
v25-governancegeschiedenis, inclusief v24-reviewerbeleid,
v23-handtekeningen, v22-herberekening, onderliggende auditketens en
de extern aangeleverde onafhankelijke begin- en eindankers.
De JSON-uitkomst `palaco.go20-governance-hardening-verdict.v1`
kan `evidence_valid: true` aangeven, maar verleent geen rechten.

De governance-uitkomst blijft onder alle omstandigheden
`decision: HOLD`, `authorization: DENY`,
`release_authorized: false`, `merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.

**Grenzen:** deze beveiligingslaag handelt alleen lokaal aangeleverde
bewijspakketten af. Zij vervangt geen onafhankelijke key custody,
feitelijke organisatiecontrole, externe onveranderlijke opslag,
productiebevoegdheden of autorisatiepoort op GitHub.
De nieuwe regressies zijn toegevoegd aan de bestaande advisory CI.
GO-13 blijft HOLD en PR #109 blijft Draft, zonder merge of uitrol.

## V27 — geconsolideerd beveiligingsacceptatierapport en herverificatie

`scripts/pr_security_acceptance.py` maakt een deterministisch,
**niet-ondertekend**, alleen-lezen eindrapport van de offline GO-20
beveiligings- en governancecontroles.

```sh
python3 scripts/pr_security_acceptance.py \
  --history governance-history.json \
  --independent-pin independent-governance-history-pin.json \
  --controller-trust independently-provisioned-controller-keys.json

python3 scripts/pr_security_acceptance.py \
  --history governance-history.json \
  --independent-pin independent-governance-history-pin.json \
  --controller-trust independently-provisioned-controller-keys.json \
  --verify-report previously-recorded-security-report.json

python3 -m unittest discover -s tests -p 'test_pr_security_acceptance.py' -v
```

Het rapport (`palaco.go20-security-acceptance.v1`) bevat een
SHA-256 van de drie volledige brononderdelen en afzonderlijke
componenthashes: `history`, `independent_pin` en
`controller_trust`. De technische v26-hardeningverdict en
expliciete acceptatiecriteria zijn opgenomen, samen met een
`report_sha256` van het volledige rapport zonder de eigen hash.

De verifier (`palaco.go20-security-acceptance-verdict.v1`)
**herberekent** de volledige v26-verificatie met de v25-,
v24-, v23-, v22-, v21- en onderliggende audit- en
getuigencontroles uit de afzonderlijk aangeleverde bewijsbronnen.
Hij accepteert geen ontbrekende of extra rapportvelden, gewijzigde
componenthashes, gemanipuleerde gate-uitkomsten, vervalste
release-statussen of gewijzigd auditbewijs. Technische acceptatie
vereist dat alle volgende criteria als waar worden herberekend:

- bounded_evidence
- signed_governance_chain
- independent_anchor_binding
- reviewer_role_separation
- signed_audit_and_witness_history
- release_prohibition

Deze gatevelden zijn een **samengevatte uitkomst** van de
complete v26-verificatie, niet zes afzonderlijke nieuwe
beveiligingsalgoritmen. Een negatieve onderliggende verificatie
betekent dat alle criteria `false` worden; de foutcodes zijn
terug te vinden in `verification.errors`.

Het rapport is geen onafhankelijk opgeslagen, digitaal
ondertekend of van een betrouwbaar tijdstempel voorzien
bewijsstuk: `independently_attested: false`. De caller moet
de oorspronkelijke bronnen en de werkelijk onafhankelijke
ankers gescheiden aanleveren. Een geldig rapport betekent
uitsluitend dat de **aangeleverde bronnen** bij herberekening
een technisch consistent resultaat opleveren.

**Geen uitvoeringsrechten:** zelfs bij
`technical_acceptance: true` en `acceptance_valid: true`
blijven `decision: HOLD`, `authorization: DENY`,
`release_authorized: false`, `merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD. PR #109 blijft Draft; geen merge, geen uitrol.

## V28 — extern ondertekend eindrapport en onafhankelijk anti-rollbackanker

`scripts/pr_final_report_attestation.py` controleert een
Ed25519-ondertekende attestatie van het **volledig opnieuw
berekende** v27-beveiligingsrapport. De module is uitsluitend
een offline verifier: zij maakt geen sleutels of handtekeningen
aan, schrijft geen bewijsregister en autoriseert geen uitrol.

```sh
python3 scripts/pr_final_report_attestation.py \
  --attestation signed-final-report.json \
  --security-report final-security-report.json \
  --history governance-history.json \
  --independent-governance-pin independent-governance-pin.json \
  --controller-trust independent-governance-controllers.json \
  --attestation-trust independent-report-signers.json \
  --independent-attestation-pin independent-attestation-pin.json
# Bij een hoger volgnummer ook: --previous-attestation signed-previous.json
python3 -m unittest discover -s tests \
  -p 'test_pr_final_report_attestation.py' -v
```

De envelop `palaco.go20-final-report-attestation.v1` bevat
`statement`, `signer_key_id` en `signature_ed25519_hex`.
De ondertekende, domeingescheiden statement heeft schema
`palaco.go20-final-report-statement.v1` en bindt:
`repository`, `sequence`, `previous_attestation_sha256`,
`report_sha256`, `decision: HOLD` en
`authorization: DENY`. Ed25519 tekent de ruwe 32 SHA-256-bytes
van de canonieke JSON-statement, overeenkomstig de
bestaande v17–v27-PALACO-handtekeningconventie.

Het afzonderlijk beheerde sleutelregister
(`palaco.go20-final-report-trust.v1`) bevat per
`signer_key_id` de `public_key_hex`, actuele
`status: active|revoked` en de verplichte
`role: attestation_custodian`. De attestatiesleutel mag
niet gelijk zijn aan een reviewer- of governancecontrollersleutel
uit de aangeleverde governancegeschiedenis.

De **onafhankelijk vastgelegde** pin gebruikt
`palaco.go20-final-report-pin.v1`, met
`expected_sequence` en `previous_attestation_sha256`.
Bij het genesisvolgnummer `0` is de voorganger verplicht
64 hexnullen. Voor een vervolgattestatie moet het afzonderlijk
aangeleverde vorige attest overeenkomen met de onafhankelijke
voorgangerhash, exact het vorige volgnummer hebben en een
geldige actieve Ed25519-handtekening bevatten. Verkeerde
volgnummers, ontbrekende voorgangers, ingetrokken ondertekenaars,
mismatches met de rapporthash of vervalste status worden
afgewezen.

**Bewijsgrenzen:** de pin en het sleutelregister worden niet
zelfstandig gepubliceerd, op versheid gecontroleerd of
onveranderlijk opgeslagen. Bij meerdere historische
attestaties valideert v28 de actuele attestatie en de direct
voorgaande, geankerde attestatie; dit is **geen volledig
onafhankelijk bewijs** van alle oudere schakels of van een
betrouwbaar tijdstip. De oorspronkelijke audit- en
governancegeschiedenis wordt door de v27-verifier wel volledig
herberekend. Externe sleutelbezit- en rolgovernance moet
afzonderlijk worden vastgesteld. Deze code mag uitsluitend
een technisch `attestation_valid`-oordeel geven; iedere
uitkomst behoudt `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`, `deployment_authorized: false`
en `production_commit_performed: false`. GO-13 HOLD,
PR #109 Draft; geen productieactie.

## V29 — volledige final-report-attestatieketen en tweezijdige sleutelrotatie

`scripts/pr_final_attestation_history.py` verifieert in uitsluitend
leesmodus **alle** aangeleverde Ed25519-attestaties vanaf genesis tot
de extern geankerde laatste attestatie. Anders dan de éénstapscontrole
in v28, controleert v29 ieder historisch ketenverband en iedere
onderliggende v27-beveiligingsrapportage opnieuw.

```sh
python3 scripts/pr_final_attestation_history.py \
  --history final-attestation-history.json \
  --custodian-trust independently-managed-attestation-keys.json \
  --independent-pin independently-retained-full-chain-pin.json
python3 -m unittest discover -s tests -p 'test_pr_final_attestation_history.py' -v
```

Het journal gebruikt `palaco.go20-final-attestation-history.v1`
met één tot zestien `entries`, ieder met `envelope`,
`report` en `inputs`, en een `rotations`-array.
De verifier gebruikt de bestaande v28-Ed25519-controle voor
elk volgnummer, controleert iedere `previous_attestation_sha256`
vanaf de verplichte genesisvoorganger (64 hexnullen) en vereist dat
alle beveiligingsrapporten onafhankelijk uit hun meegeleverde
governance- en auditbronbestanden kunnen worden herberekend.

De afzonderlijk vooraf vastgelegde
`palaco.go20-final-attestation-history-pin.v1` bindt
`genesis_attestation_sha256`, `last_sequence` en
`last_attestation_sha256`. Een afgebroken of verkorte
geschiedenis kan niet positief eindigen als de externe pin
niet mee is aangepast. Iedere hash- of handtekeningwijziging,
rollback van een volgnummer of beschadigde tussenschakel
leidt tot een negatieve technische beoordeling.

Een verandering van `signer_key_id` vereist exact één
`palaco.go20-attestation-key-rotation.v1`-overgang,
met het oude en nieuwe sleutel-ID, het volgnummer en de
hashes van de twee betrokken attestaties. De overgang
moet door **beide actieve Ed25519-sleutels** zijn ondertekend;
identiek publiek sleutelmateriaal is niet als rotatie
toegestaan. De verifier gebruikt uitsluitend het afzonderlijk
aangeleverde, actuele custodian-trustregister. Een
ingetrokken sleutel, ontbrekende tegenhandtekening,
ongeautoriseerde verandering of onnodige rotatie
veroorzaakt afwijzing.

**Grenzen:** het eerste en laatste ketenanker moeten
onafhankelijk en betrouwbaar worden beheerd, en het
sleutelregister moet een onafhankelijke en actuele bron
hebben. De verifier haalt geen sleutels op, beheert geen
sleutelrotatie, publiceert geen attestaties, verifieert
geen betrouwbare tijdstempels en kan onzichtbare
niet-gepubliceerde forks niet ontdekken. Dit is geen
feitelijke organisatieattestatie en geen productie-releasegate.
Iedere uitkomst blijft `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft; geen merge of uitrol.

## V30 — vergelijking van onafhankelijke attestatiegeschiedenissen

`scripts/pr_attestation_multiview.py` vergelijkt **twee tot acht**
afzonderlijk aangeleverde, onafhankelijk geankerde v29-attestatieketens.
De controle is uitsluitend offline en alleen-lezen.

```sh
python3 scripts/pr_attestation_multiview.py \
  --views separately-supplied-attestation-views.json \
  --independent-pins independently-retained-observer-pins.json
python3 -m unittest discover -s tests -p 'test_pr_attestation_multiview.py' -v
```

Het bronpakket gebruikt `palaco.go20-attestation-multiview.v1` met
`views`: per waarnemer een unieke `view_id`, de volledige v29
`history` en het onafhankelijk aangeleverde `custodian_trust`.
Het afzonderlijk beheerde register
`palaco.go20-attestation-multiview-pin.v1` koppelt exact
dezelfde `view_id`-waarden aan hun individueel geankerde
v29-begin- en eindhash en laatste volgnummer.

**Eerst volledige verificatie, daarna vergelijking:** iedere
aangeleverde keten moet afzonderlijk cryptografisch slagen,
inclusief complete historische publicaties, rapportherberekening,
tweezijdig ondertekende sleutelrotaties en begin- en eindankers.
De verifier weigert een ongeldige, verkorte, vervalste of
onvoldoende geankerde waarnemersweergave. Alleen na positieve
verificatie van **alle** afzonderlijke weergaven worden de
gemeenschappelijke volgnummers vergeleken. Verschillende hashes
op hetzelfde volgnummer resulteren in `fork_detected: true`,
`fork_sequences` en `conflicting_signed_attestations`.
Een kortere aantoonbaar consistente historische prefix is
toegestaan; afwijkende genesisankers, tegenstrijdige
sleutelidentiteiten voor hetzelfde signer-ID en onderling
conflicterende ondertekende rotatierecords leiden tot afwijzing.

De JSON-verdict
`palaco.go20-attestation-multiview-verdict.v1` bevat de
fouten, geverifieerde weergaven, forkvolgnummers en aantallen
gecontroleerde rotaties. De module is geen transparant
publicatieregister of gossipservice: ze bewijst uitsluitend
consistentie van de **daadwerkelijk aangeleverde**,
afzonderlijk geankerde en geverifieerde weergaven.
Niet-aangeleverde publicaties of een verborgen fork
worden niet gevonden. Verschillende `view_id`-waarden
bewijzen geen organisatorische onafhankelijkheid van
de waarnemers. Sleutels, ankers en bewaarbeleid moeten
extern betrouwbaar zijn geprovisioneerd.

Een positieve technische beoordeling geeft nooit
toestemming voor uitvoering. Iedere uitkomst bevat
`decision: HOLD`, `authorization: DENY`,
`release_authorized: false`, `merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft, zonder merge of uitrol.

## V31 — ondertekende waarnemersankers en controle van beheergrenzen

`scripts/pr_observer_anchor_custody.py` controleert in uitsluitend
leesmodus de **afzonderlijk aangeleverde, ondertekende** verklaringen
van twee tot acht waarnemers. De v30-ketenverificatie wordt altijd
opnieuw uitgevoerd; een geldige waarnemershandtekening volstaat nooit
om ongeldige of conflicterende attestatiegeschiedenis te accepteren.

```sh
python3 scripts/pr_observer_anchor_custody.py \
  --views separately-supplied-attestation-views.json \
  --history-pins independently-retained-v30-history-pins.json \
  --signed-anchors signed-observer-anchor-receipts.json \
  --observer-trust independently-provisioned-observer-custody.json \
  --independent-heads externally-retained-observer-receipt-hashes.json
python3 -m unittest discover -s tests \
  -p 'test_pr_observer_anchor_custody.py' -v
```

De ondertekende receipts (`palaco.go20-observer-anchor-bundle.v1`)
bevatten een uniek `view_id`, een domeingescheiden
`palaco.go20-observer-anchor-statement.v1` en
`signature_ed25519_hex`. Iedere statement bindt
`repository`, `view_id`, een geheel `epoch`,
`history_pin_sha256` (de hash van de afzonderlijk vastgelegde
v30-view-pin), `organization_id`, `control_domain_id`,
`decision: HOLD` en `authorization: DENY`.

Het extern beheerde waarnemersregister
(`palaco.go20-observer-custody-trust.v1`) bevat de actuele
Ed25519-`public_key_hex`, `status`, `organization_id` en
`control_domain_id` per `view_id`. De verifier weigert
ingetrokken sleutels en **overlap** in publieke sleutels,
organisatie-ID's of sleutelbeheerdomeinen. De aparte
`palaco.go20-observer-anchor-pins.v1` bevat voor iedere
waarnemer een eerder vastgelegde `minimum_epoch` en de
`receipt_sha256`. Daardoor worden teruggedraaide epochs,
mismatches met de extern bewaarde receipthash en vervalste
handtekeningen afgewezen. Ontbrekende, dubbele of extra
waarnemers ontbreken nooit stilzwijgend in het resultaat:
volledige identiteit- en pin-dekking is verplicht.

De validator vereist bovendien opnieuw een positieve v30-
multiviewcontrole, inclusief alle v29-ondertekende
attestatiegeschiedenissen, sleutelrotaties, historische
eindrapporten en hun onafhankelijke ankers. De uitvoer
`palaco.go20-observer-anchor-verdict.v1` bevat
`anchors_valid`, `observers_verified`, de volledige
`multiview_verdict` en foutcodes.

**Grenzen:** deze module creëert **geen duurzame opslag**,
publieke transparantiedienst, onafhankelijke identiteitscontrole,
onafhankelijk sleutelbeheer of automatische monitoring.
Zij controleert uitsluitend de onafhankelijk **aangeleverde**
bewaarankers en claims. Verschillende organisatie-ID's bewijzen
niet dat de eigenaars werkelijk onafhankelijk zijn; verborgen
forks worden niet gevonden. Werkelijke duurzaamheid vereist
extern beheerde onveranderlijke opslag en authenticatie van het
register. Alle uitkomsten blijven `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`, `deployment_authorized: false`
en `production_commit_performed: false`.
GO-13 HOLD, PR #109 Draft; geen merge of productie-uitrol.

## V32 — historische waarnemersankers, sleutelintrekkingen en continuïteit

`scripts/pr_observer_anchor_history.py` verifieert in alleen-lezen
modus twee tot acht achtereenvolgende waarnemersepochs.
Elke epoch bevat de vijf benodigde v31-bronnen:
`views`, `history_pins`, `signed_anchors`,
`observer_trust` en `independent_heads`. De module voert
**voor iedere epoch opnieuw** de volledige v31- en v30-verificatie
van ondertekende waarnemersankers en attestatiegeschiedenis uit.

```sh
python3 scripts/pr_observer_anchor_history.py \
  --history observer-anchor-history.json \
  --independent-pin externally-retained-observer-history-pin.json \
  --revocations independently-managed-observer-revocations.json
python3 -m unittest discover -s tests -p 'test_pr_observer_anchor_history.py' -v
```

Het historyschema `palaco.go20-observer-anchor-history.v1`
bevat `epochs` en `rotations`. De onafhankelijke
`palaco.go20-observer-history-pin.v1` koppelt
`first_epoch`, `last_epoch`, `first_snapshot_sha256`,
`last_snapshot_sha256` en `revocation_register_sha256`.
Ontbrekende epochs, herschreven begin- of eindankers en
niet-geankerde wijzigingen in het intrekkingsregister
worden afgewezen.

Het extern aangeleverde revocatieregister
(`palaco.go20-observer-revocations.v1`) bevat unieke
`public_key_hex`-waarden met een gehele `effective_epoch`.
Een sleutel die vanaf die epoch ingetrokken is, mag in
geen enkele geverifieerde snapshot vanaf die epoch nog als
actieve waarnemerssleutel voorkomen. Historische gebruiks-
momenten vóór de intrekking worden niet automatisch afgewezen.
Het register wordt door de code **niet** beheerd of
onafhankelijk ondertekend: de afgeleverde hash moet via
een werkelijk onafhankelijk en geauthenticeerd bewaarkanaal
zijn vastgelegd.

Een verandering van een waarnemerssleutel tussen twee
opeenvolgende epochs vereist een domeingescheiden
`palaco.go20-observer-key-rotation.v1`-verklaring,
voorzien van zowel de oude als de nieuwe Ed25519-handtekening.
Het statement bindt `epoch`, `view_id`, beide publieke
sleutels en de SHA-256-hashes van de oude en nieuwe
waarnemersattestaties. Ontbrekende, dubbele, vervalste,
gemanipuleerde of overbodige rotatierecords worden geweigerd.
Als de onderliggende attestatiegeschiedenis van een
waarnemer verandert, moet die nieuwe geschiedenis de oude
cryptografisch verifieerbare prefix behouden: verkorting,
herschrijving of fork leidt tot afwijzing.

**Grenzen:** dit is uitsluitend een verifier voor
**aangeleverde** snapshots, niet een opslag- of
sleutelintrekkingsdienst, transparantielog of onafhankelijke
klokbron. Het bewijst geen werkelijke organisatorische
onafhankelijkheid of het ontbreken van verborgen forks.
Een kwaadwillende eigenaar van zowel historie als externe
pinnen kan een valse geschiedenis presenteren. Iedere
uitkomst blijft `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft, zonder merge of uitrol.

## V33 — retentiecheckpoints en herstelverificatie voor historische waarnemers

`scripts/pr_observer_recovery.py` biedt een **alleen-lezen**
verificatiepoort voor uit een back-up gereconstrueerde
waarnemersgeschiedenis, zonder herstelactie, schrijfbevoegdheid
of productieautorisatie.

```sh
python3 scripts/pr_observer_recovery.py \
  --restored-history restored-observer-history.json \
  --v32-pin independently-retained-observer-history-pin.json \
  --revocations independently-retained-observer-revocations.json \
  --inventory recovery-checkpoint-inventory.json \
  --independent-recovery-pin independently-retained-recovery-pin.json
python3 -m unittest discover -s tests -p 'test_pr_observer_recovery.py' -v
```

De inventaris `palaco.go20-observer-recovery-inventory.v1`
bevat de volledige `history_sha256`,
`v32_pin_sha256` en `revocations_sha256`, een
repositorybinding en exact één checkpoint per historische epoch.
Elk `palaco.go20-observer-recovery-checkpoint.v1` bevat
`epoch`, `snapshot_sha256`,
`previous_checkpoint_sha256` en
`checkpoint_sha256`, berekend als SHA-256 van de canonieke
checkpoint-inhoud zonder het eigen hashveld. De keten begint met
64 hexnullen en sluit zonder ontbrekende of herschikte snapshots.

Een afzonderlijk aangeleverde
`palaco.go20-observer-recovery-pin.v1` legt
`inventory_sha256`, `first_checkpoint_sha256`,
`last_checkpoint_sha256`, `last_epoch` en
`minimum_epochs` vast. De verifier toetst deze exacte
referenties vóór technische acceptatie, weigert verkorte
retentiegeschiedenis en herberekent bovendien alle oorspronkelijke
v32-controles, inclusief v31-v30-ankers, handtekeningen,
revocaties en onderliggende attestatieketens.

Het resultaat `palaco.go20-observer-recovery-verdict.v1`
rapporteert `recovery_evidence_valid`,
`historical_chain_valid`, `checkpoints_verified` en
de precieze foutcodes. Een geldig resultaat is slechts bewijs
van **overeenstemming met aangeleverde herstelreferenties**.
Het bewijst niet dat die referenties onafhankelijk of duurzaam
zijn opgeslagen, noch dat back-ups feitelijk herstelbaar zijn.
De module maakt geen back-up, schrijft geen opslag,
herstelt geen bestand en beschikt niet over een betrouwbare
tijdstempelservice.

Ongeacht de uitkomst blijven `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false`,
`production_commit_performed: false` en
`restore_performed: false`.
GO-13 HOLD, PR #109 Draft; geen merge, publicatie of uitrol.

## V34 — geïsoleerde herstelproef, segmentdekking en gedeeltelijk herstel

`scripts/pr_recovery_simulation.py` valideert een **volledig
gesegmenteerd herstelpakket uitsluitend in het geheugen**. Het script
schrijft niet naar schijf, herstelt geen bestanden, opent geen database
en raakt geen productieomgeving aan.

```sh
python3 scripts/pr_recovery_simulation.py \
  --segments recovery-segments.json \
  --manifest recovery-segment-manifest.json \
  --independent-pin independent-segment-manifest-pin.json
python3 -m unittest discover -s tests \
  -p 'test_pr_recovery_simulation.py' -v
```

Het bronpakket `palaco.go20-recovery-segments.v1` bevat `parts`,
elk met de exacte velden `name` en `content`. Verplicht zijn
`epoch:0` tot en met `epoch:N-1` (2–8 epochs) en de afzonderlijke
segmenten `rotations`, `v32_pin`, `revocations`,
`inventory` en `recovery_pin`. De historische
waarnemerssleutelrotaties blijven een eigen segment en veranderen
het strikt bestaande v33-inventarisschema niet.

Het `palaco.go20-recovery-segment-manifest.v1` bevat een
repositorybinding, het aantal epochs, een `history_sha256` en
een exact `segment_sha256` voor elk segment. Het afzonderlijk
bewaarde `palaco.go20-recovery-segment-pin.v1` bevat
`manifest_sha256` en `expected_epochs`. De proef weigert
ontbrekende, dubbele, onbekende, gewijzigde of extra segmenten,
en een aangepast manifest zonder overeenkomende onafhankelijke pin.
De volgorde van aangeleverde fragmenten is niet relevant: de
historie wordt **tijdelijk** op basis van expliciete namen
gereconstrueerd.

Na controle van alle segmenten vergelijkt de verifier de
samengestelde historische SHA-256-hash met het manifest en
herberekent alle v33-herstelcontroles, inclusief onafhankelijke
retentiecheckpoints, waarnemersgeschiedenis, intrekkingen,
ondertekende attestaties en gouvernancecontroles.
Er is geen echte bestandsrestauratie of opslagreconstructie.

`palaco.go20-recovery-simulation-verdict.v1` rapporteert
`simulation_valid`, `segments_verified`,
`recovery_evidence_valid`, foutcodes en vaste
`restore_performed: false` en `write_performed: false`.
Iedere uitkomst behoudt `decision: HOLD`,
`authorization: DENY`, `release_authorized: false`,
`merge_authorized: false`, `deployment_authorized: false`
en `production_commit_performed: false`.

**Grenzen:** de validator vertrouwt op onafhankelijk beheerde
pinnen en bronbestanden; hij kan niet bewijzen dat gegevens
daadwerkelijk van fysieke back-upmedia kunnen worden hersteld,
of dat extern gepresenteerde opslag onveranderlijk is. Een
productieherstelprocedure vereist een afzonderlijk goedgekeurd
operationeel plan. GO-13 HOLD en PR #109 Draft.

## V35 — transactionele herstelproef met foutinjectie en atomische rollback

`scripts/pr_recovery_transaction.py` voert een **afgeschermde
SQLite-hersteltransactie uit in een nieuwe `:memory:`-database**.
Een volledig positief v34-herstelsimulatieverdict is verplicht
**vóór** de transactie wordt gestart. De test kan geen externe
database of productiegegevens bereiken en kent geen opslagpad
of productie-DSN.

```sh
python3 scripts/pr_recovery_transaction.py \
  --segments recovery-segments.json \
  --manifest recovery-segment-manifest.json \
  --independent-pin independent-segment-manifest-pin.json
# Negatieve herstelproeven:
python3 scripts/pr_recovery_transaction.py \
  --segments recovery-segments.json \
  --manifest recovery-segment-manifest.json \
  --independent-pin independent-segment-manifest-pin.json \
  --inject-fault before_commit
python3 -m unittest discover -s tests -p 'test_pr_recovery_transaction.py' -v
```

De transactiesimulator heeft een geïsoleerde tabel voor
herstelonderdelen en een tweede tabel voor het manifestgebonden
commitbewijs. De transactie gebruikt `BEGIN IMMEDIATE`,
controleert het exacte aantal ingevoerde onderdelen en de
SHA-256-hash van het aangeleverde manifest, en commit pas nadat
alle invarianten zijn vastgesteld. Er zijn drie doelgerichte
foutinjecties: `after_begin`, `after_first_segment`
en `before_commit`. Bij iedere geforceerde fout volgt
`ROLLBACK`, waarna de simulator controleert dat beide
tabellen leeg zijn en er geen open transactie overblijft.

Het verdict `palaco.go20-recovery-transaction-proof.v1`
maakt onderscheid tussen `sandbox_commit_performed`
(alleen een commit in de tijdelijke, afgesloten SQLite-database),
`rollback_verified`, `sandbox_rows_after_transaction`
en `transaction_valid`. Geforceerde foutscenario's leveren
een negatief technisch verdict op, zelfs als rollback correct
werd uitgevoerd.

**Beveiligingsgrens:** een succesvolle sandboxcommit is **geen
herstel in PALACO**, geen fysieke back-uptest en geen externe
datawarehouse- of PostgreSQL-commit. De module heeft geen
bestandsherstel, productietransactie, databaseconnectie of
autorisatiemechanisme. Iedere uitkomst behoudt
`decision: HOLD`, `authorization: DENY`,
`restore_performed: false`,
`production_commit_performed: false`,
`production_write_performed: false`,
`release_authorized: false`,
`merge_authorized: false` en
`deployment_authorized: false`.
GO-13 HOLD; PR #109 Draft, geen merge of uitrol.

## V36 — concurrerende herstelclaims, idempotentie en conflictisolatie

`scripts/pr_concurrent_recovery.py` simuleert **maximaal twaalf
gelijktijdige herstelclaims** tegen één nieuwe, tijdelijke SQLite
`:memory:`-database. Voor **ieder** verzoek wordt eerst de
volledige v34-herstel- en governanceverificatie uitgevoerd;
een ongeldig verzoek verhindert de hele batch, voordat een
SQL-transactie kan beginnen.

```sh
python3 scripts/pr_concurrent_recovery.py \
  --requests concurrent-restore-claims.json
python3 -m unittest discover -s tests \
  -p 'test_pr_concurrent_recovery.py' -v
```

Het JSON-bronschema `palaco.go20-concurrent-restore-requests.v1`
bevat `requests`. Iedere claim bevat exact `request_id`,
`segments`, `manifest` en `independent_pin`.
Binnen de geïsoleerde ledger geldt:

- Exact gelijke `request_id` plus dezelfde SHA-256-hashes
  van manifest, pin en segmenten: `idempotent_replay`.
- Andere `request_id` met exact dezelfde drie hashes:
  eveneens een replay; geen tweede tijdelijke ledger-commit.
- Een bestaande `request_id` met een gewijzigde combinatie
  van hashes: `request_id_conflict`, strikt negatief verdict.
- Een nieuw, onafhankelijk geldig herstelbewijs met uniek
  materiaal: maximaal één `new_sandbox_commit`.

De SQL-ledger gebruikt zowel een unieke `request_id` als
een unieke combinatie van `manifest_sha256`,
`pin_sha256` en `segments_sha256`. Een expliciet
threadslot beschermt het transactievenster, zodat de
`BEGIN IMMEDIATE`/controle/`COMMIT`-cyclus onder
meerdere testthreads serialiseerbaar is. De bronvolgorde
van het testresultaat is stabiel gerangschikt op de
oorspronkelijke index, ook als de aanroepen elkaar
overlappen.

De uitkomst `palaco.go20-concurrent-restore-verdict.v1`
rapporteert `new_sandbox_commits`,
`idempotent_replays`, `conflicts_rejected`,
`sandbox_ledger_rows` en de afzonderlijke
`request_outcomes`.

**Grenzen:** het slot en de ledger bestaan uitsluitend
binnen één procesaanroep en verdwijnen na beëindiging.
Dit bewijst **geen** idempotentie over meerdere servers,
herstarts of productiedatabases; geen productie-DSN,
bestandsherstel of daadwerkelijke persistente commit is
aanwezig. V36 vraagt geen wijziging van het bestaande
GO-13-beleid en geeft geen rechten. Iedere uitkomst
behoudt `decision: HOLD`, `authorization: DENY`,
`restore_performed: false`,
`production_commit_performed: false`,
`production_write_performed: false`,
`release_authorized: false`, `merge_authorized: false`
en `deployment_authorized: false`. PR #109 blijft Draft.

## V37 — cross-session idempotentie in disposable PostgreSQL

De uitsluitend voor CI bestemde SQL-fixture
`tests/go20_postgres_recovery_idempotency.sql` introduceert een
geïsoleerd `go20_v37`-schema in de tijdelijke PostgreSQL-dienst.
De tabel bevat een unieke aanvraag-ID en een unieke combinatie
van SHA-256-hashes van herstelmanifest, onafhankelijk anker
en herstelonderdelen. De testfunctie `go20_v37.try_claim`
kent uitsluitend de uitslagen `TEST_ONLY_COMMIT`,
`REPLAY`, `CONFLICT`, `INVALID_INPUT` en
`UNRESOLVED_CONCURRENCY`. Een status is nooit een
bevoegdheid of toestemming om een productieherstel uit te voeren.

De runner `tests/run_go20_postgres_recovery_idempotency_disposable.sh`
dwingt de bestaande GitHub Actions-bevestiging
`CI_GO20_DISPOSABLE_PG=yes` af en gebruikt uitsluitend
`127.0.0.1:5432` met de geïsoleerde database
`go20test`. De runner toetst:

- Herhaling met dezelfde aanvraag-ID en hetzelfde materiaal
  vanuit een **nieuwe databaseverbinding** zonder tweede commit.
- Een andere aanvraag-ID met hetzelfde materiaal als replay,
  en dezelfde aanvraag-ID met afwijkend materiaal als conflict.
- Ongeldige invoer zonder databasewijziging.
- Expliciete `ROLLBACK` en gesloten clientsessies vóór commit,
  waarbij geen gedeeltelijke claim achterblijft.
- Acht gelijktijdige PostgreSQL-clients met identiek
  bewijsmateriaal: precies één testcommit, zeven replays.
- Idempotentie bij opnieuw verbinden na de race.

Dit is een database-contractproef, **geen daadwerkelijke
servercrash/herstart**, geen cluster- of failovertest, en geen
duurzaam productie-register. De database blijft een wegwerpdienst
en de functie is geen publiek toegankelijke productie-API.
Bewijsverificatie gebeurt in de v34–v36-laag; de PostgreSQL-test
ontvangt alleen vooraf berekende synthetische hashwaarden en
claimt dus niet zelfstandig cryptografische bronverificatie.

De PostgreSQL-fixture is niet voor migratie naar productie
bedoeld. Geen wijzigingen aan live database, geen
toegangsverruiming, geen merge of release. GO-13 HOLD en
`authorization: DENY` blijven ongewijzigd. PR #109 blijft Draft.

## V38 — backendonderbreking, transactionele rollback en hernieuwde claims

`tests/run_go20_postgres_recovery_faults_disposable.sh` voert
een reproduceerbare negatieve herstelproef uit op de **tijdelijke
PostgreSQL-container** van GitHub Actions. De runner weigert
uitvoering zonder `GITHUB_ACTIONS=true` en
`CI_GO20_DISPOSABLE_PG=yes`, en gebruikt uitsluitend de
afgeschermde database `go20test` op `127.0.0.1:5432`.
De proef gebruikt het bestaande synthetische v37-claimsregister
en vereist dat de v37-CI-stap vooraf is geslaagd.

```sh
CI_GO20_DISPOSABLE_PG=yes \
  bash tests/run_go20_postgres_recovery_faults_disposable.sh
```

De v38-controle omvat:

1. Een afzonderlijke PostgreSQL-client start `BEGIN` en
   schrijft een synthetische testclaim binnen zijn transactie.
   Voor `COMMIT` blijft de client geblokkeerd in
   `pg_sleep`. De controller vindt de uitsluitend voor deze
   proef gemarkeerde backend via `application_name` en
   beëindigt die met `pg_terminate_backend`.
   Daarna moeten het totale rijenaantal en de afwezigheid
   van de onvoltooide aanvraag exact overeenkomen met de
   toestand vóór de onderbreking.
2. Een nieuwe databaseverbinding claimt dezelfde invoer:
   één `TEST_ONLY_COMMIT`, daarna exact `REPLAY`.
   Hetzelfde aanvraag-ID met afwijkend materiaal resulteert
   in `CONFLICT`, zonder extra claim.
3. Een tweede synthetische transactie krijgt een
   server-side `statement_timeout` nadat de testclaim is
   ingevoegd maar voordat is gecommit. Die mislukking mag
   geen database-record bewaren. Een nieuwe client kan
   de claim daarna exact eenmaal committeren en herhalen.

Dit test **backendbeëindiging en een query-timeout**, niet het
fysiek crashen of herstarten van de PostgreSQL-server,
niet het uitvallen van opslag en niet echte replicatie of
clusterfailover. Er worden geen productiegegevens of
externe databases gebruikt. De testfunctie retourneert
`TEST_ONLY_COMMIT` als synthetische technische uitkomst,
nooit als release- of herstelautorisatie.

**Veiligheidsbesluit:** GO-13 blijft `HOLD`,
`authorization: DENY`. PR #109 blijft Draft; geen
merge, publicatie, productiemigratie of werkelijk herstel.

## V39 — PostgreSQL-crashherstel en duurzaamheid van testclaims

De **laatste stap** in de bestaande `disposable-postgres`-CI-job
draait `tests/run_go20_postgres_recovery_crash_disposable.sh`.
De runner controleert vóór een ingreep beide verplichte
GitHub Actions-/wegwerptestvariabelen, een lokale verbinding
met database `go20test`, het bestaan van de geïsoleerde
v37-claimadministratie en **precies één** Docker-container
die poort 5432 publiceert. Het image moet overeenkomen
met de verwachte PostgreSQL 17-service en de container
moet `POSTGRES_DB=go20test` bevatten. Zonder deze
controles weigert de runner te draaien.

De proef gebruikt uitsluitend synthetische hashwaarden en
afzonderlijke testaanvraag-ID's. Eerst wordt een claim
**gecommit**, daarna start een tweede client een transactie
die een andere claim invoegt maar vóór `COMMIT` blijft
wachten. Na bevestiging van de actieve transactie volgt
`docker kill --signal=SIGKILL` op **alleen de geïdentificeerde
tijdelijke PostgreSQL-container**, gevolgd door
`docker start` van exact diezelfde container.

Na herstel moet PostgreSQL's WAL-herstel garanderen dat:
1. de vóór de crash gecommitte claim behouden is;
2. de bij de crash niet-gecommitte claim ontbreekt;
3. het totale rijenaantal niet onverwacht is veranderd;
4. een herhaalde gecommitte claim `REPLAY` oplevert;
5. de gecommitte aanvraag-ID met ander materiaal `CONFLICT`
   oplevert;
6. de eerder afgebroken claim eenmaal opnieuw kan committen,
   waarna herhaling uitsluitend `REPLAY` oplevert.

De stap wordt **na alle andere disposable PostgreSQL-tests**
uitgevoerd. De runner bevat een `bash -n`-syntaxiscontrole
en een tijdelijke uitvoerfolder met automatische opruiming.
Het GitHub Actions-jobtimeout blijft op tien minuten.

**Beperkingen:** dit is een volledige harde stop/herstart
van **één tijdelijke databasecontainer**, geen bewezen
clusterfailover, herstel van hardwarefalen of fysiek
verlies van de opslaglaag. De synthetische v37-testfunctie
voert zelf geen volledige externe v34–v36-preflight uit.
Geen productie-migratie of -herstel is voorzien.
GO-13 `HOLD`, `authorization: DENY`; PR #109 Draft.

## V40 — geïsoleerde tweedatabase-handoff, snapshotverschillen en failover-DENY

`scripts/pr_recovery_handoff.py` vergelijkt twee gestructureerde
exports van het **synthetische v37-herstelclaimsregister**.
Iedere rij bevat exact `request_id`, `manifest_sha256`,
`pin_sha256` en `segments_sha256`. De controle toetst
unieke aanvraag-ID's en uniek bewijsmateriaal, het volledige
rijenaantal, en exacte canoniek gesorteerde records. Een
afzonderlijk aangeleverd `palaco.go20-restore-handoff-pin.v1`
bevat de bron-SHA-256 en een `minimum_rows`-retentiegrens.
De verifier weigert ontbrekende, extra, dubbele, gewijzigde
of gemanipuleerde records en een mismatch met het bronanker.
Een consistente snapshot verleent **nooit** failoverrechten;
het verdict bevat altijd `decision: HOLD`,
`authorization: DENY` en `failover_authorized: false`.

De nieuwe CI-runner
`tests/run_go20_postgres_handoff_disposable.sh` maakt een
**tweede, afzonderlijke PostgreSQL 17-wegwerpcontainer**
op lokale poort 5433, met tijdelijke gebruikersgegevens.
De bestaande primaire disposable CI-database blijft op 5432.
De runner loopt vóór de v39-crashproef en ruimt de tweede
container en zijn tijdelijke bestanden bij beëindiging op.

De test voert eerst een `pg_dump`-/`psql`-snapshotkopie van
het geïsoleerde `go20_v37`-schema uit. Een exact gelijke
snapshot moet slagen. Daarna wordt op de primaire
wegwerpdatabase een extra claim gecommit, terwijl de kopie
achterloopt: de verifier **moet weigeren**. Een nieuwe
snapshotkopie herstelt de overeenstemming. Een opzettelijk
gemanipuleerde claim op de kopie moet opnieuw worden
geweigerd. Er zijn veertien aparte Python-regressietests
in `tests/test_pr_recovery_handoff.py`.

```sh
python3 -m unittest discover -s tests -p 'test_pr_recovery_handoff.py' -v
# Uitsluitend vanuit disposable GitHub Actions CI:
bash tests/run_go20_postgres_handoff_disposable.sh
```

**Belangrijke grenzen:** dit is snapshotgebaseerde overdracht
tussen twee werkelijk afzonderlijke, maar tijdelijke databases.
Er is **geen** streamingreplicatie, synchrone WAL-replicatie,
fysieke promotie, leader election, quorum, fencing of
automatische failover. De CI-fixture maakt de bronhash zelf
en bewijst dus geen onafhankelijke operationele bewaarketen;
bij werkelijke toepassing moet de pin vooraf onafhankelijk
en geauthenticeerd worden vastgesteld. Dit bewijst ook niet
dat opslag op twee machines fouttolerant is. Er zijn geen
productiemigraties of live herstelacties. GO-13 HOLD,
PR #109 Draft, geen merge, uitrol of productieaanpassing.

## V41 — fail-closed fencingbewijs, split-brainpreventie en epochbinding

`scripts/pr_recovery_fencing.py` valideert **uitsluitend
aangeleverd bewijsmateriaal** voor de overgang tussen twee
databaseknooppunten. De verifier is geen clustercontroller:
hij schakelt geen knooppunten uit, promoveert geen replica,
kiest geen leider en geeft geen productiebevoegdheid.

```sh
python3 scripts/pr_recovery_fencing.py \
  --primary primary-recovery-claims.json \
  --candidate candidate-recovery-claims.json \
  --handoff-pin independently-retained-v40-handoff-pin.json \
  --transition observer-fencing-evidence.json \
  --independent-pin independently-retained-fencing-transition-pin.json
python3 -m unittest discover -s tests -p 'test_pr_recovery_fencing.py' -v
```

Het bewijspakket `palaco.go20-recovery-fencing-evidence.v1`
bindt `repository`, `previous_epoch`,
`candidate_epoch`, `old_writer_id`, `candidate_id`,
`node_roles`, `fencing_ack` en `handoff_sha256`.
De onafhankelijke `palaco.go20-recovery-fencing-pin.v1`
bindt de canonieke `transition_sha256`, minimale epoch
en de afzonderlijk verwachte knooppuntidentiteiten.

Het controlecontract vereist één hoger opvolgende epoch,
twee verschillende knooppuntidentiteiten, het oude knooppunt
in rol `fenced` en het nieuwe knooppunt in rol
`candidate` (dus **nog niet** `writer`). De
`fencing_ack` benoemt expliciet het gefencete knooppunt,
dezelfde nieuwe epoch, een positieve bewijsclaim en een
niet-lege `control_domain`. Een ontbrekende bevestiging,
gelijktijdig schrijvende knooppunten, een extra schrijver,
verouderde epochs en niet-aangeleverd extern anker worden
afgewezen.

Daarnaast wordt de volledige v40-handoffcontrole
opnieuw uitgevoerd. Beide claimadministraties moeten
dezelfde gegevens bevatten en overeenstemmen met het
onafhankelijk aangeleverde bronanker; de hash van de
bronadministratie moet ook overeenkomen met de
`handoff_sha256` in het fencingbewijs. Afwijkende
of ontbrekende transacties blokkeren de beoordeling.

Het verdict `palaco.go20-recovery-fencing-verdict.v1`
rapporteert `fencing_evidence_valid`, gecontroleerde
epochs, aantallen vergeleken records en foutcodes.

**Strikte grenzen:** de huidige `fencing_ack` is
een aangeleverde, hashgebonden claim, **geen
cryptografisch geauthenticeerd fencingbewijs** en geen
controle of een eerder schrijvend knooppunt werkelijk
geen toegang meer heeft. Verschillende node-ID's of
beheerdomeinnamen bewijzen geen onafhankelijke beheerders.
Split-brain wordt alleen gedetecteerd wanneer strijdige
rollen in aangeleverde gegevens staan. Voor echte
failover zijn geauthenticeerde fencing, quorum/lease-
beheer, een betrouwbare controlebron en aparte
autorisatie vereist.

Zowel bij positief als negatief technisch resultaat
blijven `decision: HOLD`, `authorization: DENY`,
`fence_performed: false`,
`failover_authorized: false`,
`promotion_performed: false`,
`release_authorized: false`, `merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD, PR #109 Draft; geen merge of uitrol.

## V42 — ondertekende fencingverklaringen met extern vastgelegde quorumgrens

`scripts/pr_signed_fencing_quorum.py` herverifieert de volledige
v41-fencingketen en vereist bovendien **Ed25519-handtekeningen**
van ten minste twee onafhankelijke stemmers, waaronder de
extern aangewezen `fence_controller`. De quorumgrens mag
strenger zijn: `minimum_signatures` komt uit het onafhankelijke
`palaco.go20-fencing-quorum-pin.v1` en mag maximaal het
aantal geregistreerde stemmers bedragen.

```sh
python3 scripts/pr_signed_fencing_quorum.py \
  --primary primary-recovery-claims.json \
  --candidate candidate-recovery-claims.json \
  --handoff-pin independent-v40-pin.json \
  --transition v41-transition.json \
  --transition-pin independent-v41-pin.json \
  --signed-votes signed-fencing-quorum-votes.json \
  --trust independently-provisioned-fencing-keys.json \
  --independent-pin independent-v42-pin.json
python3 -m unittest discover -s tests -p 'test_pr_signed_fencing_quorum.py' -v
```

Het onafhankelijke vertrouwensregister
`palaco.go20-fencing-quorum-trust.v1` bevat drie tot
zeven stemmers met elk een publieke Ed25519-sleutel,
organisatie-ID, beheerdomein-ID, rol en sleutelstatus.
Een opgegeven stem telt uitsluitend als de sleutel actief
is, de handtekening correct is en er geen overlap is met
eerder meegetelde organisaties, domeinen of sleutels.

Een ondertekend statement met schema
`palaco.go20-fencing-quorum-statement.v1` bindt
repository, `candidate_epoch`, `transition_sha256`,
`trust_sha256`, `member_id`, `decision: HOLD` en
`authorization: DENY`. De ondertekening is een
Ed25519-handtekening over de bytes van de canonieke
SHA-256-hash van dat statement. De onafhankelijke pin
bindt bovendien de hashs van het vertrouwensregister en
de overgangsverklaring, een minimale epoch, een minimaal
aantal geldige handtekeningen en de identiteit van de
vereiste fencingcontroller.

De verifier weigert vervalste, dubbele, ontbrekende of
ongeldige stemmen; ingetrokken sleutels; overlappende
beheerclaims; onvoldoende quorum; ontbrekende
controllerstem; gewijzigde onafhankelijke ankers;
teruggedraaide epochs; en iedere ongeldige v41-handoff.
Het resultaat `palaco.go20-signed-fencing-quorum-verdict.v1`
bevat `quorum_evidence_valid`, `signatures_verified`
en foutcodes.

**Grenzen:** een cryptografische stem bevestigt alleen
de ondertekende verklaring. Dit is geen bewijs dat een
fysieke fencingactie is uitgevoerd, geen onafhankelijk
identiteitsonderzoek naar organisaties, geen consensus-
of leaseprotocol, en geen productiequorumsysteem.
Onafhankelijke provisioning, authentieke key custody,
vertrouwde externe pinopslag en fysieke fencing blijven
vereiste afzonderlijke beveiligingsmaatregelen.

Ook bij een positief technisch resultaat blijven alle
bevoegdheden geblokkeerd: `decision: HOLD`,
`authorization: DENY`, `fence_performed: false`,
`promotion_performed: false`,
`failover_authorized: false`,
`release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft, geen merge of productie-uitrol.

## V43 — historische fencingquorums, intrekkingen en dubbel ondertekende sleutelrotaties

`scripts/pr_fencing_quorum_history.py` controleert een
**aangeleverde reeks van 2–6 opeenvolgende quorum-epochs**,
waarvan iedere snapshot opnieuw de volledige v42-check op
Ed25519-stemmen, onafhankelijk sleutelregister, fencingbewijs,
replicatie-snapshots en GO-13-governance doorloopt.

```sh
python3 scripts/pr_fencing_quorum_history.py \
  --history historical-fencing-quorums.json \
  --independent-pin independent-historical-quorum-pin.json \
  --revocations independent-fencing-key-revocations.json
python3 -m unittest discover -s tests \
  -p 'test_pr_fencing_quorum_history.py' -v
```

Het `palaco.go20-fencing-quorum-history.v1`-object
bevat `snapshots` en `rotations`. Per snapshot zijn
alle v42-bewijsbronnen, een gehele `epoch` en
hun bijbehorende onafhankelijke pinnen vereist.
De afzonderlijk bewaarde
`palaco.go20-fencing-quorum-history-pin.v1`
bevat het exacte begin- en eind-epoch, SHA-256-ankers
van beide eindmomenten, de hash van de gehele historie
en de hash van het intrekkingsregister.

Het extern beheerde
`palaco.go20-fencing-quorum-revocations.v1`-register
bevat unieke publieke sleutels en een gehele
`effective_epoch`. Vanaf die epoch mag een ingetrokken
sleutel niet meer actief zijn in een geverifieerde
quorumsnapshot. Historische epochs vóór intrekking
blijven geldig mits hun oorspronkelijke bewijs intact
is. Dubbele of gewijzigde revocaties worden geweigerd.

Een sleutelverandering tussen twee epochs vraagt een
`palaco.go20-fencing-quorum-key-rotation.v1`-statement
met `epoch`, `member_id`, oude en nieuwe sleutel en
de hashes van beide volledige quorumvertrouwensregisters.
De **oude én nieuwe sleutel** moeten het statement
afzonderlijk met Ed25519 ondertekenen; hergebruik van
oude verklaringen, onjuiste rotatiebinding, vervalste
handtekeningen of onverklaarde sleutelwijzigingen
leiden tot een negatief verdict.

Tussen opeenvolgende snapshots controleert de module
de continuïteit van de knooppuntketen, stabiele
quorumleden, een niet-dalende minimumquorumgrens,
een niet-dalende epochgrens en strikte epochopvolging.
De historie mag niet stilzwijgend worden ingekort
of herschreven.

Het verdict `palaco.go20-fencing-quorum-history-verdict.v1`
rapporteert `history_valid`, `epochs_verified`,
`rotations_verified` en afzonderlijke foutcodes.

**Grenzen:** dit is een offline bewijsverifier, geen
onafhankelijk opgeslagen of ondertekend intrekkingsregister,
geen fysieke sleutelbewaarplaats en geen bewijs dat
fencing werkelijk is uitgevoerd. Vertrouwensankers
moeten **vooraf** via een authentiek onafhankelijk kanaal
zijn vastgelegd. Er bestaat geen nieuwe uitvoering-,
productie- of failoverbevoegdheid.
`decision: HOLD`, `authorization: DENY`,
`fence_performed: false`, `promotion_performed: false`,
`failover_authorized: false`, `release_authorized: false`,
`merge_authorized: false`, `deployment_authorized: false`,
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft, geen merge of uitrol.

## V44 — onafhankelijk ondertekende intrekkingen en detectie van historische forks

`scripts/pr_signed_revocation_fork.py` vereist een **Ed25519-ondertekende
verklaring** over de v43-intrekkingsregisterhash, de vooraf vastgelegde
historiehash en een minimale epoch. De sleutel-ID en de Ed25519-publieke
sleutel worden uit een **afzonderlijk aangeleverde pin** betrokken; ze
worden niet uit de ondertekende verklaring zelf vertrouwd.

```sh
python3 scripts/pr_signed_revocation_fork.py \
  --left-history quorum-history-left.json \
  --left-pin independently-retained-left-history-pin.json \
  --right-history quorum-history-right.json \
  --right-pin independently-retained-right-history-pin.json \
  --revocations quorum-revocations.json \
  --signed-register externally-signed-revocations.json \
  --independent-pin independently-retained-revocation-fork-pin.json
python3 -m unittest discover -s tests \
  -p 'test_pr_signed_revocation_fork.py' -v
```

De externe `palaco.go20-signed-revocation-fork-pin.v1` bevat
`trusted_key_id`, `trusted_public_key_hex`,
`revocations_sha256`, `history_sha256` en
`minimum_epoch`. Het statement
`palaco.go20-revocation-register-statement.v1` bindt deze
historische referenties expliciet aan repository en
`HOLD / DENY`. De Ed25519-handtekening wordt gecontroleerd
tegen het onafhankelijk vertrouwde publieke sleutelmateriaal.

Twee apart aangeleverde en zelfstandig gepinde v43-geschiedenissen
worden **beide volledig** gecontroleerd op quorums, sleutelrotaties,
effectieve revocaties en continuïteit. Daarna vergelijkt de verifier
hun canonieke SHA-256-hashes met elkaar en met de vooraf vastgelegde
externe historiehash. Zelfs wanneer beide geschiedenissen elk op
zichzelf cryptografisch geldig zijn, leidt een verschil tot
`historical_fork_detected`. Ongelijke epochvensters, een
teruggedraaide minimumepoch en ontbrekende of gewijzigde revocaties
geven aparte fouten.

Het verdict `palaco.go20-revocation-fork-verdict.v1` geeft
`historical_evidence_valid`, `histories_verified`,
`epochs_verified` en de foutcodes. De tests omvatten onder meer
handtekeningvervalsing, sleutelvervanging, een niet-geautoriseerde
registerupdate, inkorting van historie, twee verschillend
ondertekende geldige quorumtakken en replay van oude verklaringen.

**Grenzen:** de onafhankelijke pin en vertrouwenssleutel moeten
daadwerkelijk via een extern geauthenticeerd kanaal worden beheerd;
een lokaal door dezelfde partij vervangen pin is geen echte
onafhankelijkheidswaarborg. Het systeem beschikt niet over een
publieke transparantielog of netwerkbreed forkdetectieprotocol.
Een geldig technisch bewijs verleent geen herstel-, merge-,
fencing- of failoverbevoegdheid. Iedere uitkomst blijft
`decision: HOLD`, `authorization: DENY`,
`fence_performed: false`, `failover_authorized: false`,
`promotion_performed: false`, `release_authorized: false`,
`merge_authorized: false`, `deployment_authorized: false`
en `production_commit_performed: false`. GO-13 HOLD; PR #109 Draft.

## V45 — onafhankelijke Ed25519-getuigen voor transparantiecheckpoints

`scripts/pr_transparency_checkpoint_views.py` controleert
**twee tot vijf apart aangeleverde checkpointweergaven**
met hun eigen ondertekende getuigenverklaringen. De verifier
voert eerst de volledige v44-controle uit op ondertekende
intrekkingen en op twee v43-quorumgeschiedenissen.

```sh
python3 scripts/pr_transparency_checkpoint_views.py \
  --left-history quorum-history-left.json \
  --left-pin history-left-pin.json \
  --right-history quorum-history-right.json \
  --right-pin history-right-pin.json \
  --revocations revocations.json \
  --signed-register signed-revocations.json \
  --v44-pin independent-v44-pin.json \
  --views independent-checkpoint-observations.json \
  --trust independent-witness-trust.json \
  --independent-pin independent-checkpoint-pin.json
python3 -m unittest discover -s tests \
  -p 'test_pr_transparency_checkpoint_views.py' -v
```

Het `palaco.go20-transparency-checkpoint.v1`-record
legt `repository`, `sequence`, `last_epoch`,
`history_sha256` en `revocations_sha256` vast.
Een aparte `palaco.go20-transparency-checkpoint-pin.v1`
bindt de verwachte checkpoint-SHA-256, de SHA-256 van het
getuigenregister, een minimale sequence en de quorumgrens.
Een checkpoint waarvan de hash afwijkt van dit
vooraf vastgelegde anker wordt geweigerd, ook wanneer
andere getuigen die afwijkende checkpoint rechtsgeldig
hebben ondertekend.

Het onafhankelijke `palaco.go20-transparency-witness-trust.v1`
heeft drie tot zeven getuigen, elk met publieke Ed25519-sleutel,
organisatie-ID, beheerdomein-ID en sleutelstatus. Per weergave
moeten minimaal twee verschillende actieve getuigen een
canoniek `palaco.go20-transparency-witness-statement.v1`
ondertekenen, dat de `observer_id`, `checkpoint_sha256`,
`trust_sha256`, `witness_id` en `HOLD/DENY` bindt.
De onafhankelijke quorumgrens kan strenger zijn.

De v45-testgevallen controleren onder andere:
- twee ondertekende maar onderling tegenstrijdige historieankers;
- een veranderd sequence-nummer of verouderde minimumsequence;
- onvoldoende getuigen, dubbele stemmen of dubbele observers;
- sleutelintrekking, handtekeningvervalsing en overlap in
  organisaties of beheerdomeinen;
- ongeautoriseerde wijzigingen in checkpointinhoud,
  sleutelregister, historie of intrekkingsregister.

Het verdict `palaco.go20-transparency-checkpoint-verdict.v1`
bevat `transparency_evidence_valid`, `views_verified`,
`signatures_verified` en gespecificeerde foutcodes.

**Grenzen:** er wordt geen externe logserver aangeschreven,
geen checkpoint gepubliceerd, geen gossipnetwerk gebruikt
en geen onafhankelijk netwerkquorum vastgesteld. De
getuigen en pins zijn in dit contract **aangeleverde
bewijsmaterialen**; onafhankelijke opslag, distributie,
authentieke sleutelcustody en logbeschikbaarheid blijven
separate operationele vereisten. Een positief technisch
resultaat autoriseert niets: `decision: HOLD`,
`authorization: DENY`,
`checkpoint_published: false`,
`fence_performed: false`,
`failover_authorized: false`,
`promotion_performed: false`,
`release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false`,
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft; geen merge of productie-uitrol.

## V46 — checkpointopvolging, ondertekende ontvangstbewijzen en publicatiegaten

`scripts/pr_checkpoint_receipt_continuity.py` verifieert een
**aangeleverde reeks van 2–6 opeenvolgende checkpoints**
met Ed25519-ondertekende ontvangstverklaringen. De
`palaco.go20-checkpoint-receipt-continuity.v1`-keten
bevat `entries`; elk item heeft `sequence`,
`previous_entry_sha256`, `checkpoint` en
`receipts`. Het eerste item verwijst naar de
nulhash; elk volgend item verwijst naar de canonieke
SHA-256 van het volledige voorafgaande item, inclusief
ontvangstbewijzen.

```sh
python3 scripts/pr_checkpoint_receipt_continuity.py \
  --chain checkpoint-receipt-chain.json \
  --independent-pin independent-chain-anchor.json \
  --trust independent-witness-keys.json \
  --v45-evidence validated-v45-evidence-bundle.json
python3 -m unittest discover -s tests \
  -p 'test_pr_checkpoint_receipt_continuity.py' -v
```

De onafhankelijk vastgelegde
`palaco.go20-checkpoint-receipt-continuity-pin.v1`
bevat `first_sequence`, `last_sequence`,
`first_entry_sha256`, `last_entry_sha256`,
`trust_sha256` en `quorum`. De verifier verlangt
exact aaneensluitende nummers, overeenkomende
hashkoppelingen en de correcte begintoestand en eindhash.
De laatste checkpoint moet exact gelijk zijn aan de
volledig opnieuw geverifieerde v45-checkpointweergave.

Iedere ontvangstverklaring ondertekent met Ed25519
een `palaco.go20-checkpoint-delivery-receipt.v1`
statement dat repository, checkpointnummer,
checkpointhash, voorgaande entry-hash, vertrouwensregister,
ontvangeridentiteit en `HOLD/DENY` bindt.
Een afzonderlijk gepind quorum van minimaal twee
unieke actieve getuigen met niet-overlappende
organisaties en domeinen is per checkpoint vereist.
Ontbrekende, hergebruikte, dubbele, vervalste of
ingetrokken getuigenbewijzen worden geweigerd.

Voor een positieve technische uitspraak wordt ook de
v45-verificatie uitgevoerd, inclusief de onderliggende
v44-ondertekende revocaties en de v43-historische
quorumcontrole. De module doet geen netwerkverzoeken.

**Grenzen:** de ontvangstbewijzen zijn aangeleverde,
cryptografisch te verifiëren *claims*; de module kan
niet vaststellen dat een externe transparantiedienst
de checkpoint werkelijk duurzaam heeft gepubliceerd
of dat alle mogelijke checkpoints ooit werden aangeleverd.
Echte onafhankelijkheid vereist vooraf authentiek
bewaarde pins, een openbaar controleerbare log,
externe beschikbaarheidscontrole en onafhankelijke
getuigeninfrastructuur.

Het verdict `palaco.go20-checkpoint-receipt-continuity-verdict.v1`
rapporteert `publication_evidence_valid`,
`checkpoints_verified`, `receipts_verified` en
foutcodes; **ook een technisch geldige keten** houdt
`checkpoint_published: false`,
`remote_publication_verified: false`,
`decision: HOLD`, `authorization: DENY`,
`fence_performed: false`,
`failover_authorized: false`,
`promotion_performed: false`,
`release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false` en
`production_commit_performed: false`.
GO-13 HOLD; PR #109 Draft; geen merge of productie-uitrol.

## V47 — onafhankelijke checkpointbewaring en fail-closed herstel bij ontbrekende getuigen

`scripts/pr_checkpoint_retention_custody.py` controleert
**twee tot vijf aangeleverde, ondertekende archiefkopieën**
van een volledige v46-checkpointketen. De verifier controleert
de **gehele** oorspronkelijke v46→v45→v44-bewijsketen
opnieuw; een ontbrekende originele handtekening of
onvoldoende quorum kan nooit worden gerepareerd door
uitsluitend een kopie van het bewijs aan te leveren.

```sh
python3 scripts/pr_checkpoint_retention_custody.py \
  --chain checkpoint-chain.json \
  --chain-pin independent-v46-pin.json \
  --witness-trust independent-v46-witness-trust.json \
  --v45-evidence all-v45-inputs.json \
  --archive externally-collected-archive-copies.json \
  --custodians independent-archive-custodians.json \
  --independent-pin independent-v47-retention-pin.json
python3 -m unittest discover -s tests \
  -p 'test_pr_checkpoint_retention_custody.py' -v
```

Het `palaco.go20-checkpoint-retention-pin.v1`-anker
legt de canonieke SHA-256 van de volledige keten en
het afzonderlijk vastgelegde register van archiefbeheerders
vast, plus minimaal twee beheerders, de kleinste
toegestane checkpointsequentie en de ondergrens voor
het aantal behouden checkpoints. Elke archiefkopie
bevat de volledige originele checkpointketen en een
Ed25519-handtekening over
`palaco.go20-checkpoint-retention-receipt.v1`,
met expliciete binding aan ketenhash, begin- en
eindsequentie, beheerregisterhash, beheerderidentiteit
en `HOLD/DENY`.

Het externe register
`palaco.go20-checkpoint-custodian-trust.v1`
bevat actieve publieke sleutels, organisatie- en
beheerdomeinidentiteiten. De verifier weigert dubbele
beheerders, overlappende domeinen en organisaties,
vervalste handtekeningen, ingetrokken beheerders,
afwijkende archiefkopieën, gewijzigde pins,
teruggedraaide checkpointsequenties en aantasting
van de oorspronkelijke quorumketen.

Het verdict `palaco.go20-checkpoint-retention-verdict.v1`
bevat `custody_evidence_valid`,
`checkpoints_archived`, `custodians_verified`
en foutcodes. Een positief technisch resultaat
toont uitsluitend **consistent aangeleverde,
ondertekende archiefverklaringen**, niet werkelijk
actuele fysieke of externe beschikbaarheid.

**Geen onbewezen claim:** deze module bevraagt geen
externe opslaglocatie, garandeert geen retentieduur,
voert geen herstel uit en bevestigt geen onafhankelijke
operationele sleutelcustody. Archiefkopieën leveren
geen autorisatie, kunnen ontbrekend oorspronkelijk
getuigenquorum niet vervangen en maken geen
publicatiebewijzen aan. Daarom zijn
`physical_availability_verified: false`,
`restoration_performed: false`,
`missing_witness_quorum_overridden: false`,
`checkpoint_published: false`,
`fence_performed: false`,
`failover_authorized: false`,
`promotion_performed: false`,
`release_authorized: false`,
`merge_authorized: false`,
`deployment_authorized: false`,
`production_commit_performed: false`,
`decision: HOLD` en `authorization: DENY`.
GO-13 HOLD; PR #109 Draft, geen merge of productie-uitrol.
