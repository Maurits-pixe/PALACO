# Hannie B D-013 — eerste aparte SQLite-candidate v0.1 DRAFT

Nieuwe module modules/hara/hannie-b-d013, eigen branch hara/hannie-b-d013-sqlite. Gepubliceerde codecommit 48a332dc19761626c55cd238835b19ec1f617a8f, base c2a5e4059c21ef11a498f85bf3499a65ccfdfc92. Lokale geteste codecommit 07618741ce1af30a6b606b272b37552d95723c09. Scope-bytebinding in publish-binding.json; oude PR #36 en R2 blijven buiten deze wijziging. Geen deny-PASS hergebruikt.

## Werkelijk gebouwd en getest

Eén lokale CREATE-transactie met authorization decision, shared auditsequence, effect, immutable eventversion, exact approval consumption en receiptbinding. Revoke op dezelfde SQLite-ordering. De writer wordt abrupt SIGKILL'ed, vóór of na COMMIT en in de native COMMIT/WAL-route. De supervisor negeert positieve ACK's van de writer en laat een nieuw read-only proces reconstrueren. Recovery doet geen tweede write.

Formele run e0d86fb6-fd13-43a3-8628-87a64a5a5af6: Node v24.19.0, Linux, gcc-native fixture. 15 tests / 15 PASS / 0 FAIL / 0 skipped / 0 cancelled. Bronset vóór/na identiek: e8b9cb9ba232fef8808d82d2d860c50cd17a7c9cbec0e52733217483936db1b6. Eigen source/artifacthashcheck PASS. Raw TAP en afzonderlijke B-proces/native traces staan in de runmap. Dit is builder-evidence, geen onafhankelijke review of officiële PROOF.

B01: post-COMMIT SIGKILL, besluit/effect/versie/receipt/consumption overleven in nieuw proces vóór expiry. B02: crash vóór COMMIT, nul effecten. B03: valse precommit-ACK wordt genegeerd. B04/B05/B13: revoke-first geen effect, commit-first historische toestand behouden en nieuwe inhoudsvrijgave geblokkeerd, echte concurrente ordering. B06/B11: verloren ACK/replay/concurrente duplicates, één effect. B07–B09: exact digest/generation/context en receiptcorruptie. B10: echte SQLite-lockwait voorbij expiry geeft deny. B14: native SIGKILL tijdens COMMIT vóór WAL-write, geen crash-overlevende toestand en geen succes.

## Expliciet tegenbewijs en acceptatiegrens

B12 forceert een echte 900 ms WAL-stall over expiry. Een vroeg precommitObservedAt wordt niet als decisionAt opgevoerd. Het resultaat is COMMITTED_RESULT_WITHHELD / DEADLINE_NOT_PROVEN, geen SUCCEEDED en geen agenda-inhoud. **Er blijft een laat effect achter.** Recovery bewaart dat bewijs en schrijft niet opnieuw of wist het niet. Geen claim van nul late effecten of absolute storage-deadlinegarantie.

Returned decisionAt/effectAt zijn post-crash readback-upperbounds op dezelfde commit; geen exacte fsync-timestamps, geen geattesteerde ERA-tijd, geen tweede duurzame autorisatie. De durable receiptbinding krijgt geen tweede write. Deze DERIVED meetwijze en het late-effectrestrisico vereisen onafhankelijke contractreview. Algemene D-013-acceptatie blijft HOLD; 15/15 betekent uitsluitend de expliciete lokale controls.

Eerste ontwikkelrun ce0c20c8-6beb-471d-91b6-1c34461dd26a: 5 PASS / 9 FAIL omdat de fixturecontrole null-prototype SQLite-rows als plain JSON probeerde te canoniseren. Dat fixtureprobleem is hersteld zonder runtime-autorisatie te versoepelen. De gefaalde run is behouden, niet als PASS herlabeld. Tussenruns 26337798-33fd-4043-9fde-4a9cee421976 en 9a336e8e-e90c-4ed6-8eb6-4a23aad5ae04: elk 14/14 vóór toevoeging van de native COMMIT-interruptcontrol; geen vervanging van de formele 15-run.

## Niet in deze slice

Provider-/D1-dispatch, externe restore-/trust-epoch, live identiteit/admission, persona-reviewflow, integratie, productie, merge en officiële PROOF. Grants/context en event zijn uitsluitend synthetische fixturegegevens. Geen echte agendaactie.

## AI-review: één builder, drie lenzen

TRIAS: D-013 in eigen contracttekst; één crash-surviving transaction en geen authority uit ACK/prepare. ORACLE: echte SIGKILL/nieuwe-processreadback, native late-durabilitytegenbewijs en bronhashes; geen deny-evidence als B-bewijs. MENTOR: candidate is gericht en uitvoerbaar; onafhankelijk beoordelen van upperbound-meetwijze en late-effectrestrisico voordat acceptatie sluit.

Werkstatus IMPLEMENTED / LOCAL CONTROLS PASS. Verificatie beperkt tot bovengenoemde run/omgeving. Onafhankelijke review PENDING; ACCEPTANCE HOLD / INTEGRATION HOLD / PRODUCTION HOLD. NOT MERGED / NOT DEPLOYED / PROOF NOT ISSUED. Volgende geldige overgang: de aparte B-envelop beoordelen op eigen contract en nieuwe evidence; geen nieuwe deny-suite-review. Nieuwe CI wordt afzonderlijk aan de gepubliceerde head gebonden.
