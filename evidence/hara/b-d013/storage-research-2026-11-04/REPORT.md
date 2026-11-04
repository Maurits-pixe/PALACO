# HARA — opslagonderzoek onder ongewijzigd D-013

Datum 2026-11-04. DERIVED RESEARCH, geen productadapter of nieuw canonbesluit. Baseline PR #98 head 0a9697ec84516cb528be277fe93d9b2afc654d52. Aanvulling op D013-RUNTIME-DECISION-2026-11-04.md. De deadline blijft de crash-overlevende SQLite-commit van besluit en effect vóór expiry.

## Uitgevoerde concrete proef

Nieuwe geïsoleerde Python/SQLite-proef met één synthetische rij, WAL, synchronous=FULL, native 900 ms pwrite-vertraging, en echte SIGKILL van de writer na de API-uitkomst. Een nieuwe read-only SQLiteverbinding in de supervisor leest de toestand na die crash. De fixtureverbinding blijft open om WAL te behouden en verricht geen verdere writes. Dit is geen nieuw readerproces, stroomuitvalproef of volledige Hannie/D-013-acceptatietest.

Uitvoering: Python 3.12.14, SQLite 3.53.1. Native injector opnieuw gecompileerd met gcc; bron wal-stall.c hergebruikt als fixture, geen historische PASS hergebruikt. Probe.py, compiler.stderr, per-case JSON, summary.json en unsigned SHA256-binding zijn opgenomen.

| Scenario | API-uitkomst | Rijen na writer-SIGKILL | Conclusie |
| --- | --- | --- | --- |
| Progress-handler, geen stall, geldig bij start | commit zonder fout | 1 | Positieve controle |
| Progress-handler, al expired vóór COMMIT | OperationalError: interrupted | 0 | Negatieve controle |
| Progress-handler elke instructie + WAL-stall | OperationalError: interrupted | 1 | API-fout is hier geen bewijs van afwezigheid van commit |
| Watchdog roept interrupt op expiry + WAL-stall | commit zonder fout | 1 | Interrupt sluit late duurzaamheid niet |
| Progress-handler en watchdog samen + WAL-stall | OperationalError: interrupted | 1 | Combinatie sluit de grens evenmin |

Alle drie stalltraces beginnen vóór expiry en eindigen erna; gemeten wachttijd minstens 900 ms. De native pauze zit vóór de echte pwrite. De rij blijft na daadwerkelijke writercrash zichtbaar. De trace is geen exact fsync-tijdstip of ERA-attestatie. Dit zijn vijf uitgevoerde scenario's, geen claim van algemene conformance. De Python/SQLite-runtime is anders dan de Node-candidate; het resultaat is mechanismeonderzoek, geen vervangend Node-bewijs.

## Primaire documentatie en betekenis

Op 4 november gelezen, beknopt geparafraseerd:

- [SQLite interrupt](https://www.sqlite.org/c3ref/interrupt.html): onderbreking gebeurt bij een beschikbare gelegenheid; een bijna voltooide operatie kan nog afronden. Dit ondersteunt geen absolute storage-deadline.
- [SQLite progress handler](https://www.sqlite.org/c3ref/progress_handler.html): callbackfrequentie is gekoppeld aan VM-instructies, geen gedocumenteerd maximum voor een blokkerende I/O-operatie.
- [SQLite commit hook](https://www.sqlite.org/c3ref/commit_hook.html): de hook kan de commit laten doorgaan of rollback afdwingen; de documentatie geeft geen deadlinebewaking gedurende de daaropvolgende I/O. Niet afzonderlijk geprogrammeerd/getest in deze proef.
- [SQLite WAL](https://www.sqlite.org/wal.html): commitrecord wordt aan WAL toegevoegd; FULL synchroniseert bij commit. Een commitmechanisme is nog geen real-time deadlinegarantie. De atomiccommit-pagina beschrijft primair rollback-journaling en is niet als WAL-specificatie gebruikt.
- [PostgreSQL 18 timeoutdocumentatie](https://www.postgresql.org/docs/18/runtime-config-client.html): statement_timeout begrenst statementduur, transaction_timeout sessieduur binnen een transactie, lock_timeout lockwacht; prepared transactions vallen buiten transaction_timeout. Deze pagina bewijst geen D-013-conforme duurzaamheid vóór een absolute grant-expiry. PostgreSQL is hier NIET UITGEVOERD of uitgesloten als universeel onmogelijk; een migratie zou eigen mechanisme- en crashtests vragen.

## Selectiebesluit binnen onderzoeksscope

Geen onderzochte route wordt geselecteerd voor runtime-implementatie als deadlineoplossing. SQLite progress/interrupt is voor deze claim door de proef verworpen. Commit-hook en PostgreSQL-timeouts zijn niet als oplossing aangetoond. Een VFS die alleen vóór pwrite of sync expiry controleert verplaatst de check; zonder een onderbouwde grens voor de daaropvolgende persistence is dat geen deadlinebewijs (DERIVED, niet gebouwd).

De vereiste capability blijft: deadlinehandhaving op het werkelijk crash-overlevende commitpunt, met geldige klok-/storageaannames, en gedeelde revoke-ordering. In de geraadpleegde bronnen en de uitgevoerde proef is geen ondersteunde implementatie met die capability vastgesteld. Dit is geen bewijs dat alle denkbare opslagarchitecturen onmogelijk zijn.

Geen TTL, latere cleanup, content-withholding of nieuwe logische autorisatiegrens als stilzwijgende vervanging. D-013 behouden betekent hier runtime HOLD, totdat een passende storagegarantie met bewijs beschikbaar is. Andere deadlinesemantiek vereist een expliciet nieuw bevoegd contractbesluit zoals in het beslisdossier uitgewerkt.

## Review en vervolgovergang

AI-review aan de hand van drie lenzen door dezelfde bouwer: TRIAS bewaart D-013 en authoritygrenzen; ORACLE onderscheidt nieuwe experimentele tegenvoorbeelden, documentatie-inferenties en niet uitgevoerde routes; MENTOR stopt migratie of runtimebouw zonder aantoonbaar passend opslagmechanisme. Geen onafhankelijke acceptatie of officiële PROOF.

Status RESEARCH EXECUTED / THREE LATE-EFFECT COUNTEREXAMPLES OBSERVED / COMPLIANT STORAGE ROUTE NOT ESTABLISHED / ACCEPTANCE HOLD. Volgende geldige stap: aantoonbare storagecapability met deadlinegarantie beoordelen; of een expliciet opdrachtgeversbesluit voor een ander contract voorbereiden. Onder het huidige contract is vrijgave van positieve mutaties niet gerechtvaardigd.

## Reproduceren

Vanuit deze directory: `python3 probe.py`. Vereist Linux, Python met sqlite3, gcc en glibc. De proef compileert stall.so en schrijft results/. Bewaar de gepubliceerde oorspronkelijke results vóór een nieuwe uitvoering. Dit zijn synthetische tijdelijke databases, geen echte agenda's, grants of accounts. De SHA256-binding controleert bytes en is geen authenticiteitshandtekening.
