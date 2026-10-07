# H∆R∆ — D-012 herbouw · overdracht aan onafhankelijke review

**IMPLEMENTED · LOCAL CHECKS PASS · CI PASS · INDEPENDENT REVIEW PENDING · OVERALL ACCEPTANCE HOLD · INTEGRATION HOLD · PRODUCTION HOLD · NOT DEPLOYED.**

Nieuwe geïsoleerde herbouw **0.3.3-d012.1** op `hara/hannie-agenda-candidate-v0.3` in `Maurits-pixe/PALACO`. De Notion-contracten en D-011/D-012 zijn als primaire bron gebruikt. Oude candidatecode is niet gereconstrueerd, oude evidence niet vervangen. D-012-acceptatie vraagt nog de onafhankelijke review; dit rapport is de bouweroverdracht.

## Exact object en bewijsbinding

| Object | Binding |
| --- | --- |
| Baseline main | `c2a5e4059c21ef11a498f85bf3499a65ccfdfc92` |
| Eerste branchcommit, bronmanifest | `ca85ad10b1e0166d3209a66e9bd4cf4d49d2cbdd` |
| Geteste codecommit | `428c66e31f0093ad373ec80deee7425c814cb161` |
| Bronacquisitierun | `b4cf9b57-2bcf-4307-8e82-57477e01fa36` |
| Notion-bronset SHA-256 | `130506380e90ef0a5c5810061fcf0ebcaa37069978b00b80e2debe145f95be34` |
| Lokale uitvoeringsrun | `dd921d45-963e-47fb-a91b-7dfbbf497430` |
| Code/test/workflow-bronset SHA-256 | `3a5ebc62f0dc3d913c5e12987a01ff6bb1bcf8a4b57cd7301dbfc65d80070e6b` |
| UTC-uitvoering | 2026-10-04T20:38:38.883Z – 2026-10-04T20:38:51.482Z |
| Runtime | Node v24.19.0 / SQLite 3.53.3 / Linux x64 / gcc 13.3.0 |

Deze evidencecommit voegt alleen dit dossier toe; de geteste bronset blijft identiek. Bind bij review de werkelijk gekozen PR-head afzonderlijk. Alle individuele bron- en artifacthashes staan in [result.json](runs/dd921d45-963e-47fb-a91b-7dfbbf497430/result.json); de dossierhashes staan in review-package-manifest.json. De volledige private Notion-bytes zijn afzonderlijk aan de eigenaar geleverd. Het publieke source-manifest.json bindt die bytes en bevat hun bronnen, zonder de teksten te publiceren.

## Gedrag en uitgevoerde controles

Voorbereiding, revisies, grantgeneraties, exact OWNER-akkoord, revieweradvies, durable concerns, veld-/purposegebonden lezen en semantische historische recovery zijn geïmplementeerd. De adapter weigert **iedere execute-route** met `STORAGE_EFFECT_DEADLINE_UNSUPPORTED`; er bestaat geen runtime-mutationbody of effectfallback. Definitieve mutatieautorisatie is niet naar prepare/confirm/opdracht-aanvaarding verschoven.

**76/76 lokale controles PASS; 0 FAIL, 0 cancelled, 0 skipped, 0 todo.** Bronset vóór/na identiek. Raw TAP, compileruitvoer en afzonderlijke native-/reader-/waittraces zijn bewaard. De integriteitscontrole van deze bestanden én de acht private bronsnapshots is PASS; zij is een controle door de bouwer, geen onafhankelijke acceptatie.

| Benoemde controle | Waarneming in deze run | Betekenis |
| --- | --- | --- |
| Privileged WAL-primitivecalibratie | Eén native stall van 2400 ms; tweede proces ziet effect 1312 ms na expiry | Gevaaropstelling geldig; dit is geen candidate-execution |
| TIME-I01, grant en approval | Deny vóór native write; 0 effects; grants/approval/concerns/consumption onveranderd | Weigering getest |
| TIME-I02, alleen approval | Dezelfde deny en geen authoritycallbacks of WAL-write | Weigering getest |
| READ-I01, contextwait | 151 ms na expiry: CONSENT_INACTIVE, geen inhoud | Nieuwe frozen requirement control PASS |
| RECOVER-I01, contextwait | 152 ms na expiry: CONSENT_INACTIVE, geen inhoud/receiptidentiteit voor HANNIE | Nieuwe frozen requirement control PASS |
| READ-I02, policywait | 152 ms na expiry: CONSENT_INACTIVE, geen inhoud | Nieuwe frozen requirement control PASS |
| Prepare/revise/read/recover, context/policy/storagewait | Opnieuw actuele autorisatie na de dependencies; negatieve controles PASS | Geteste wachtgrenzen gedekt |
| Echte separate SQLite-writerlock | 155 ms na expiry geen inhoud; ook verlies admission/policy tijdens lock weigert | Opslagwait is werkelijk uitgevoerd |
| Ruim bevoegde positieve lees-/receiptcases | PASS met toegestane velden/receiptontvanger | Weigering van expiry is geen algemene blokkering van lezen |
| DST, digests, concernrevisies, grantreissue, rollback/restart, receiptcorruptie | PASS volgens contract-map.json en TAP | Alleen de benoemde lokale controles |

De historische FAIL-verwachtingen zijn opnieuw als frozen requirement controls geschreven uit de primaire Notion-records. **De originele historische fixturebytes zijn onbeschikbaar.** Er wordt geen byte-identieke oude reproductie, 43/86/27-historische-testequivalentie of herstel van oude candidatecode geclaimd.

Een eerdere ontwikkelrun had drie native-harness-buildfouten door een niet-gecontroleerd C-write-resultaat. Die run is als niet-acceptance vastgelegd in development/native-build-blocker.json. Daarna is alleen dat compilatieprobleem hersteld, met behoud van -Werror en de frozen verwachtingen; deze formele run compileert en slaagt. De eerdere fout is niet als PASS herlabeld.

## CI, afzonderlijk van lokale evidence

GitHub-run [37232870799](https://github.com/Maurits-pixe/PALACO/actions/runs/37232870799), event push, exacte codecommit hierboven: workflow en isolated-candidate-job **SUCCESS**. De runnerstap en evidence-uploadstap zijn SUCCESS. Artifact `hannie-d012-evidence`, ID 11314736101, digest `sha256:dee71c152db35ba1c72b9b05ec38cc84f4601ab977df05f11456b3056f2b8662` is waargenomen.

Workflow-/job-/artifactmetadata staat in ci-observation.json. CI-loginhoud en CI-result.json zijn hier **NOT RETRIEVED**; het cijfer 76/76 hierboven hoort bij de lokale run. De bestaande GO-13 Standards Conformance-workflow op dezelfde codecommit is afzonderlijk SUCCESS. CI verleent geen runtime-authority of onafhankelijke beoordeling.

## PROOF-grenzen en resterende blokkades

| Label | Scope of grens |
| --- | --- |
| SPECIFICATION | Notion-contract v0.2/v0.3 en D-011/D-012; primaire snapshots/hashbinding |
| IMPLEMENTED | Nieuwe lokale adapter en tests; eigen schema D012-1 |
| RUNTIME EXECUTED / CHECKS PASS | Alleen de 76 controles in de aangewezen lokale run |
| PROVEN_WITHIN_SCOPE | Lokale resultaatlabel voor de geteste weigering, wachtgrenzen en overige benoemde controles; geen canon- of certificeringslabel |
| CI PASS | Alleen waargenomen workflow/jobstatus op exact gebonden codecommit |
| UNVERIFIED / INDEPENDENT REVIEW PENDING | Onafhankelijke contract-/code-/hash-/frozen-controlreview niet uitgevoerd door deze bouwer |
| NOT EXECUTED / BLOCKED | Succesvolle agenda-mutaties, mutation/revoke-COMMIT-ordering, mutation-ACK/crashherstel |
| NOT EXECUTED / NOT INTEGRATED | Hosted D1, live identiteit/hostsession, modeladapters, Black/Foundation/widget/ELIXER/AM-10 |
| OPEN / UNPROVEN | AM-R01 en D-010; absolute effectdeadline, externe klok-/restoretrust |
| NOT ISSUED / NOT AUTHORIZED | Officieel HOOFDKANTOOR-PROOF, release/merge/live-authority |
| HOLD | Algemene acceptatie, functionele integratie en productie |

De laatste autorisatiesample na wachtende dependencies sluit de geteste callback-/opslaggap. Hij is **geen absolute scheduler-, netwerk-, publicatie- of fysieke COMMIT-deadlinegarantie**. De grantchecks autoriseren geen latere kalenderuitvoering.

Conservatief afgeleid: OWNER_DIRECT vraagt authenticated OWNER; HANNIE volgt de HARA-reviewroute. De gedeelde pending-CREATE-barrière is per eigen kalender. Deze DERIVED policies zijn geen bevoegd canonbesluit. Productiesessie/admissionbinding en een hostroute voor aantoonbare directe OWNER-instructies moeten later afzonderlijk worden gebonden.

## AI-review aan de hand van drie lenzen

Eén coding-assistent past alle drie lenzen toe; dit zijn geen onafhankelijke reviewers of actieve PALACO-services.

| Lens | Bevinding en evidence | Gevolg |
| --- | --- | --- |
| TRIAS | Uniforme deny-route bewaart S1/COMMIT; grant/review/concernbinding en allowlist zijn aan contract-map/tests gebonden. D-010 blijft OPEN. | GO voor overdracht binnen D-012; functionele integratie, acceptatie en productie HOLD |
| ORACLE | 76 brongebonden lokale PASS, private/source/artifacthashcontrole PASS; CI-status afzonderlijk waargenomen. Originele fixturebytes en onafhankelijk oordeel ontbreken. | Beperkte geteste uitkomst; geen absolute deadlineclaim of algemene PROOF |
| MENTOR | Geïsoleerde package zonder externe npm-dependencies, herhaalbare runner en invulbare REVIEW.md. | Reviewer kiest exacte head, vergelijkt contracten en draait eigen run met eigen evidence |

Resterend dissent: positieve lokale controles kunnen het onafhankelijke-reviewvereiste of de tijd-/effectblocker niet opheffen.

## Volgende geldige overgang

**Exacte D-012-herbouw → onafhankelijke review door de gebruiker**, zoals in de opdracht aangekondigd. Hertoets private bronhashes, leg contract-map/code naast Notion en voer frozen controls in een eigen omgeving uit. Gebruik modules/hara/hannie-agenda/REVIEW.md voor revieweridentiteit, exacte head/base, eigen runtime/run-ID/logs, findings en beperkt oordeel.

```sh
cd modules/hara/hannie-agenda
node tools/run-evidence.mjs
node tools/check-evidence.mjs /absolute/path/to/result.json /absolute/path/to/unpacked-private-source-root
```

Elke reviewer-run krijgt een nieuw run-ID; dit bouwbewijs wordt behouden. D-010 voorbereidende analyse kan daarnaast worden besproken. Zij verandert deze code of de deadlinebetekenis pas na een afzonderlijk bevoegd besluit.
