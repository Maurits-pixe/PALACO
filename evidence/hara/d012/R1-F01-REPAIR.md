# R1-F01 herstel en D-010 statusdelta — 2026-10-05

Codecommit: `0c1c99ed240bd7ba1d89512da56f5a7a5de55edd`. Voorgaande gepubliceerde PR-head: `7243e8d1e72818cbe0d17472aec6a87e8d7b109d`; base `c2a5e4059c21ef11a498f85bf3499a65ccfdfc92`. Nieuwe evidence wordt toegevoegd; het oorspronkelijke REPORT.md, bronmanifest, private hashes en R1 blijven intact.

## Resultaat

WAL-writer fork krijgt uitsluitend `--disable-warning=ExperimentalWarning`. De lege-stderr-assertie blijft bestaan; een nieuwe regressietest toont dat andere warningtypes en echte exceptions zichtbaar blijven. Alle runtime-srcbestanden en frozen-controls.json zijn byte-ongewijzigd. D010-ADDENDUM.md, README, REVIEW, contract-map en runnerstatus onderscheiden het geregistreerde B-besluit van niet-geïmplementeerde TACP-uitvoering.

## Werkelijk uitgevoerde runs

| Run | Bron / runtime | Uitkomst |
| --- | --- | --- |
| 8b44c5eb-eefd-4549-a647-250f03e4ebee | Oude head, Node 24.19.0, expliciet geïnjecteerde ExperimentalWarning | 73 PASS / 3 FAIL; diagnostische reproducer, geen standaard-runtimeclaim |
| 7b77dac3-3861-4f85-b973-a9decaddfd5d | Oude head in aparte worktree, echte Node 24.14.1 zonder warningonderdrukking | 73 PASS / 3 FAIL; R1-F01 werkelijk gereproduceerd |
| 7c1b81bc-56ad-4981-95e3-ccb637926f23 | Tussenstand met alleen harnessfix, Node 24.19.0 | 77/77 PASS; ontwikkelcontrole, geen finale acceptatie |
| 2ec7683c-77ae-444a-a653-97c679d3d45f | Finale codecommit, Node 24.19.0 standaard | 77/77 PASS |
| f3a64c26-5f3a-410f-a6a6-3951f7e2d792 | Finale codecommit, Node 24.19.0 met opgeslagen warningfixture | 77/77 PASS |
| 64b53d79-4f63-4247-a9b6-3565b911b928 | Finale codecommit, echte Node 24.14.1 standaard | 77/77 PASS |

Finale bronset vóór/na in alle drie runs identiek: `0cdef92a85d26cad4c1dd50d609e4fd8f69dc311264c0d672781a347e6551b2e`. Finale raw TAP, compileroutput en native/readertraces blijven in de benoemde runmappen. Geen skips/failures/cancelled/todo in de finale runs. Eigen hashcontrole van drie finale runs PASS; ook de echte baseline-run gecontroleerd in zijn ongewijzigde oude worktree: PASS. Private bronbytes NOT CHECKED.

De Node 24.14.1-archiefhash is vergeleken met de via HTTPS opgehaalde officiële SHASUMS256.txt: PASS, `84d38715d449447117d05c3e71acd78daa49d5b1bfa8aacf610303920c3322be`. De runner bindt bovendien de werkelijk gebruikte nodebinaryhash. Eerste tar-extractie meldde ownershipproblemen; de binary was bruikbaar en de daadwerkelijke run slaagde. Dit is geen testfailure.

Warningregressie herhalen vanuit de module:

```sh
NODE_OPTIONS=--require=$(pwd)/tests/fixtures/experimental-warning.cjs node tools/run-evidence.mjs
```

## D-010 — resterend technisch risico

Optie B is in Notion geregistreerd; duurzame TACP-beslissingsdeadline, besluit/effect in dezelfde transactie en twee receipt-tijden zijn contracteisen. Het serialization-/durabilitypunt is nog niet operationeel gebonden. Een precommit-tijdsample of SQL-insert vóór WAL-durability bewijst geen duurzame beslissingscommit vóór expiry. Zie D010-ADDENDUM.md. Geen positieve mutaties/TACP gebouwd of getoetst.

## Triade en overgang

Eén AI-assistent, drie lenzen: TRIAS bewaart deny/HOLD en originele evidence; ORACLE bindt echte before/after-runtimechecks en hashes zonder private- of onafhankelijke claims; MENTOR vraagt onafhankelijke herreview op de nieuwe exacte PR-head en daarna sluiting van het TACP-/durabilitycontract.

R1-F01: BUILDER REPAIR CHECKS PASS; onafhankelijke sluiting PENDING. D-010: BESLUIT GEREGISTREERD / IMPLEMENTATIE OPEN / ACCEPTATIE OPEN. Integratie/productie HOLD. Officiële PROOF NOT ISSUED. Merge/deployment niet uitgevoerd. Nieuwe CI moet afzonderlijk aan de nieuwe head worden gebonden; dit rapport claimt geen nieuwe CI-PASS.
