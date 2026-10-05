# Hannie B — D-013 isolated SQLite candidate v0.1 DRAFT

Scope: één atomaire SQLite CREATE-transactie met authorization decision, event, version, approval consumption, shared auditsequence en receiptbinding. Eén lokale synthetische eigenaar/kalender. Geen hostendpoint of complete Hannie-integratie.

Lees CONTRACT.md. Het writerproces sterft na COMMIT met SIGKILL. De supervisor negeert ACK's en laat een nieuw read-only proces alleen reconstrueren. SUCCEEDED vereist volledige binding plus post-crash readback vóór expiry. decisionAt/effectAt zijn herkenbaar als readback-upperbounds op dezelfde commit, niet als exact fsync-tijdstip of twee commits. De oorspronkelijke precommit-sample heet precommitObservedAt en draagt geen succes.

B12 bewaart belangrijk tegenbewijs: bij echte native WAL-vertraging over expiry blijft een laat effect mogelijk. De candidate onthoudt succes, geeft geen inhoud vrij en schrijft niet opnieuw. Zij biedt **geen garantie van nul late effecten**. Acceptatie van de tijdmeetwijze en dat restrisico is OPEN; geen algemene D-013-conformanceclaim.

De tests gebruiken werkelijk SIGKILL, SQLite-lockcontention, concurrente aparte processen, false ACK vóór COMMIT, verlorengegane ACK ná COMMIT en native pwrite/WAL-stall. De oude deny-suite wordt niet gedraaid of als nieuw B-bewijs gebruikt. De C-injector is een gewijzigde testfixture met nieuwe B-variabelen/bronhash; oude tests of PASS worden niet overgenomen.

## Uitvoeren

Linux / Node 24.14.1 of 24.19.0 / gcc / glibc / node:sqlite. Geen npm-dependencies.

```sh
cd modules/hara/hannie-b-d013
node tools/run-evidence.mjs
```

Per run nieuwe ID, raw TAP, proces-/native traces, runtime- en binaryhash, bronset vóór/na en artifacthashes. Trusted harness env is uitsluitend voor crash-/stallinjectie in deze geïsoleerde candidate. Geen callerflag verleent grant, eigenaarrol of write-authority.

Provisioning gebeurt uitsluitend in tests/fixture.mjs. Geen productiegrant of echte afspraak wordt aangemaakt. De exported execute/recover/revoke zijn lokale bouwinterfaces, geen live PALACO-service. Recovery opent de database read-only en schrijft geen receipt, event, approval of audit opnieuw.

Niet in deze slice: providers, D1, restore-/trustepoch, live identiteit, persona-reviewflow, integratie, productie, merge of PROOF. Lokale Date.now is geen geattesteerde ERA-tijd. Eén AI-builder; onafhankelijke review PENDING. Productie/integratie HOLD.

B-R1 repair requires Linux `/usr/bin/flock` and a private canonical database path. Recovery from a new supervisor withholds historical content without a deadline witness. Release scope is locked worker IPC, not a consumer/network delivery guarantee. See CONTRACT.md.
