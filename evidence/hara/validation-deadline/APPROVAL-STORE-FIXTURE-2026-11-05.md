# HARA — duurzame fixture-challenge en exact fixture-akkoord

Datum 2026-11-05. Baseline PR #105 head d92b65237dd617d02cd4521ace54db219eff34cb. Deze slice test opslag en concurrency van akkoorduitgifte, niet echte authenticatie. Runtimeworker, vastgesteld deadlineprofiel en oude D-013-code onveranderd; nieuwe code staat uitsluitend onder tests/ en wordt niet door src/index.mjs geïmporteerd of als endpoint aangeboden.

## Selectie van bestaande identiteitsbron

services/rio-accounts/src/lib.rs en storage.rs op de baseline zijn via GitHub gelezen/vergeleken met lokale bytes: gelijk. Die service verklaart zichzelf een loopback-only synthetische OIDC-/sessiegrens, beperkt tot de fictieve TST-alpha/TST-beta en scope RIO_SYNTHETIC_SESSION_TEST_V1. Het is geen echte HARA-eigenaar of bevoegdheid voor CREATE_OWN_EVENT. Daarom is geen RIO-sessie omgezet in HARA-authority, geen identityprovider omgeconfigureerd en geen credential opgevraagd/gebruikt. identity-source-review.json bindt de gelezen bronhashes en de begrensde selectieconclusie. Een echte authority-/tijdbron blijft ongebonden.

## Werkelijk gebouwd

De expliciete fixtureprovisioner gebruikt alleen een canonical calendar.sqlite direct in een hara-vd-* directory onder de OS-temproot en vaste synthetic-owner/tenant/session. Dat is een testfence, geen authenticatiemechanisme. Lokale code met database-/testworkerrechten valt buiten het fixture-threatmodel.

prepareChallenge bewaart een exact context/request/preview/expiry/approval-ID-gebonden fixturechallenge. confirmChallenge leest huidige grant/kalender, toetst het synthetische requirements-model, en legt challengeverbruik plus exact fixture-akkoord in één BEGIN IMMEDIATE-transactie vast. Hetzelfde private-path flock als de candidate ordent de processen. Goedkeuring is een synthetisch consentrecord, geen TACP of agendaeffect; de uiteindelijke mutatie houdt haar eigen onafhankelijke grant-/akkoord-/expiry-checks en atomaire decision/effectcommit.

Een writer sterft echt met SIGKILL vóór, binnen een native WAL-write of na COMMIT. De supervisor negeert ACKclaims en laat een afzonderlijk read-only proces challenge/approvalbinding reconstrueren. Ontbrekende of tegenstrijdige rijen geven UNKNOWN; geen stille reparatie, automatische tweede write of heractivering van een verbruikt akkoord. Replay reconstrueert bestaande historie. Elke succesvolle fixture-readback meldt realAuthorityGranted=false.

Een tijdens storagevertraging verlopen fixture-akkoord kan historisch blijven bestaan. Readback rapporteert expired=true en de runtime weigert daarna uitvoering zonder event. Dit is geen harde issuance-storage-deadlinegarantie of herinterpretatie van de verleende expiry.

## Nieuwe controls en evidence

Finale lokale run b414cd17-5587-4714-952c-e5596aa9c624: Node v24.19.0 Linux. Runtime 24/24 PASS; client 13/13 PASS; snapshotmodel 20/20 PASS; stateful issuance-fixture 16/16 PASS. Alle suites: 0 fail/skip/cancel/todo. Vier eigen TAPs/exits/countersets verplicht voor gecombineerde PASS. Bronset fb280b2abbb751a5f8c233d9333956725a1154dd5b8ee2e57aa9b357ff7585bf vóór/na gelijk. Exact-run verifier: 22 bronhashes en 42 artifacthashes PASS. git diff --check PASS.

I01 levert een expliciet fixture-akkoord op dat de bestaande synthetic runtime vervolgens opnieuw valideert. I02/I15 tonen rollback bij echte SIGKILL vóór/in COMMIT: challenge OPEN, geen approval. I03 toont reconstructie na commit zonder ACK. I04 start daadwerkelijk twee afzonderlijke confirmationprocessen: één approval en één verbruik. I05–I11 weigeren vreemde actor, requestwijziging, expiry, revoke, generationwijziging, ontbrekende risico-erkenning en clienttijd als expiry-omweg. I12 false ACK vóór commit geeft geen approval; I13 replay na runtimeconsumption maakt het akkoord niet opnieuw bruikbaar; I14 incomplete durable binding geeft UNKNOWN zonder repair. I16 native stall kruist expiry, historische approval expired=true en runtime DENIED / VALIDATION_DEADLINE_EXPIRED, 0 events.

I01/I02/I03/I04/I12/I13/I14/I15/I16 hebben eigen proces-/native readbacktraces in het runpakket. De state-helper neemt fixture_challenges mee zodra die tabel bestaat; equalitychecks omvatten dus ook het challengeverbruik. Een eerste 14-control-run c6525492-e645-4726-9f3b-7e07c06f6900 blijft behouden met eigen bronset; die vervangt de finale 16-control-run niet. Geen historische PASS hergebruikt. Nieuwe CI afzonderlijk aan de gepubliceerde head te binden.

## Reviews en grenzen

AI-review aan de hand van drie lenzen: TRIAS houdt fixture-authority apart van echte identity/admission en gebruikt de RIO-testscope niet als HARA-mandaat; ORACLE onderscheidt nieuwe echte database-/crashexecutie van de nog ontbrekende provider-/tijd-/restorebewijzen; MENTOR sluit één concrete opslaginterface met idempotente readback en zichtbare onbekende uitkomst. Eén AI-bouwer; formele onafhankelijke acceptatie PENDING.

De eerdere interface-eis voor atomair challengeverbruik plus approval-insert is nu als fixturemechanisme uitgevoerd. Echte credential/originverificatie, product-authority-uitgifte, externe tijd, restore-/trust-epoch en browser/accountintegratie blijven NOT IMPLEMENTED. Geen productprovider gekozen of gekoppeld. Geen real-authorityclaim uit verified-vlaggen of tests.

Status FIXTURE STORAGE IMPLEMENTED / LOCAL FOUR-SUITE CONTROLS PASS / REAL ADMISSION NOT IMPLEMENTED / INTEGRATION HOLD / PRODUCTION HOLD / PROOF NOT ISSUED. Volgende overgang: exacte head → eigen matrix-CI → beperkte opslagreview en expliciete echte authority-/tijdbronbinding vóór productadmission. Geen merge/deployment.
