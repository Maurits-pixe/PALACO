# H∆R∆ — BR06 · 31 oktober 2026

Lokale herstelcandidate: recovery valideert grant.calendar_id en grant.action opnieuw. Afwijking geeft RESULT_UNKNOWN / BINDING_MISMATCH zonder event of receipt; replay schrijft niets opnieuw.

Twee nieuwe regressies falen op oorspronkelijke runtime (before.tap). Definitieve gewijzigde bron: 22/22 PASS, 0 FAIL/skipped (final-file.tap), Node v24.19.0/Linux, inclusief echte SIGKILL, WAL-stall, revoke en expiry. git diff --check PASS. Baseline en hashes na uitvoering: manifest.json; geen voor/na-attestatie.

Cloudharnessbeperking: standaardrunnerpogingen b56ef548-b196-41d5-9d1e-34e408fc23d8, b044a056-6ac4-47fd-b7d6-a856de98ac73 en 0edc8186-1844-4fca-b2d2-0bd33f4162d8 tellen 0 tests en blijven FAIL. Directe uitvoering eerst 21 PASS / 1 FAIL: BR03 ontving lege child-stdout; ook async stdout hielp niet. Definitieve BR03 leest een fixturebestand dat het aparte supervisorproces schrijft, controleert exit en signal, en behoudt alle readonly/no-replay assertions. Standaardrunner ongewijzigd.

Reproductie vanaf repositoryroot:
```sh
gcc -shared -fPIC -O2 -Wall -Werror -o /tmp/hara-br06.so modules/hara/hannie-b-d013/tests/wal-stall.c -ldl
B013_NATIVE_LIBRARY=/tmp/hara-br06.so node --disable-warning=ExperimentalWarning --test-isolation=none --test --test-concurrency=1 --test-reporter=tap modules/hara/hannie-b-d013/tests/commit.test.mjs
```
De testharness gebruikt geen extra testfileproces; echte candidateworkers blijven aparte OS-processen. Grantcorruptie is fixturetoegang, geen claim over een publiek aanvalspad.

AI-review aan de hand van drie lenzen:
- TRIAS: bestaande bindingsgrens aangescherpt, geen nieuwe authority; historische evidence behouden.
- ORACLE: twee oorspronkelijke FAIL, daarna 22 lokale PASS; geen nieuwe CI of onafhankelijke acceptatie. Runnerbeperkingen expliciet.
- MENTOR: kleine runtimepatch en gerichte regressies; verifieer standaardisolatie afzonderlijk in CI.

Status IMPLEMENTED / LOCAL CONTROLS PASS / ACCEPTANCE HOLD. B12-late-effect blijft bestaan; readbacktijd is geen exact duurzaamheidsmoment. Integratie/productie HOLD; geen merge, deployment of PROOF.

Volgende geldige overgang: exacte patch naar afzonderlijke review en CI. Voorbereiding binnen GO; merge/integratie/activatie niet geautoriseerd.
