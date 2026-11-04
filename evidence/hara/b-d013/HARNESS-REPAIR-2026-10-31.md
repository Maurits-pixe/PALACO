# Hannie B-R1 — lokale harnessreparatie · 2026-10-31

Baseline: 1b2065af0dfe82e25b3f62c80d9f9873563f6afd. Module vóór wijziging bytegelijk aan PR #38 head 2a869dc11aa1c8e11f1f748084d8f7e617b17e42 (git diff leeg). Remote PR/CI-status niet opnieuw gecontroleerd.

Gewijzigd: tests/commit.test.mjs en tools/run-evidence.mjs. Asynchrone procesaanroepen; runner stdout/stderr via bestanden, procesfouten/signalen in result.json; BR03-resultaat via fixturebestand. Eén testbestand draait met --test-isolation=none; echte writer/reader/revoke/supervisorprocessen blijven afzonderlijk. Runtime, contract en assertions ongewijzigd.

Reden: child-process pipes gaven hier lege output. Eerste runs 5fe57971-4379-436c-9ada-a1c694ee66b1, 978e593a-adee-4acd-8aba-a30be197af79 en 878f1635-e73e-47ec-afa1-0f23eac37c65 zijn FAIL en blijven behouden. Directe diagnostiek: 19 PASS, BR03 FAIL door lege JSON-output.

Nieuwe run 15153bd5-32af-458c-94e6-4c2e7df4a613: 20/20 PASS, geen skipped/cancelled, Node v24.19.0 Linux, native GCC-injector. Bronset 672f0128cb759b03501a03e8401ab2a64c937185107ea6741eb7f300e3e1e960 vóór/na identiek. Alle bron- en artifact-SHA256 uit result.json opnieuw berekend: PASS. git diff --check PASS. Tweede Node-versie en CI NOT EXECUTED.

AI-review aan de hand van drie lenzen:
- TRIAS: harnessscope behouden; frozen evidence intact; geen authority toegevoegd.
- ORACLE: nieuwe TAP/native traces/hashbinding; mislukte runs bewaard; geen historische PASS hergebruikt. B12 late-effecttegenbewijs blijft gelden.
- MENTOR: nieuwe bronset met diff en raw evidence afzonderlijk laten reviewen; uitvoer via bestanden maakt deze omgeving reproduceerbaar.

Status: IMPLEMENTED / LOCAL CONTROLS 20/20 PASS / ACCEPTANCE HOLD / FORMAL INDEPENDENT ACCEPTANCE PENDING. Volgende overgang: lokale herstelrevisie → afzonderlijke review en CI op beide Node-versies. Geen integratie/productie/merge/PROOF-vrijgave. Geen nul-late-effectgarantie.
