# Hannie B-candidate — D-013 SQLite-contract v0.1 DRAFT

Primaire bron: [D-013](https://app.notion.com/p/8a4f35ebe743499088178364ec04c58d), opdrachtgever 2026-10-05. Baseline PR #36 head 8660ce4453ec67c04e8a65de8e56c9edba089bb5 blijft frozen buiten deze candidate/R2. Dit is één nieuwe, geïsoleerde B-candidate. Geen deny-PASS is B-bewijs.

## Vastgestelde contractgrens

TACP is de crash-overlevende SQLite-commit van besluit en effect in één transactie. Geen in-memory akkoord, precommit-sample, twee duurzame momenten, of als geslaagd gemelde commit die de procescrash niet overleeft. Deadline gehaald uitsluitend als de crash-overlevende commit vóór expiry bereikt is. Revoke vóór die commit blokkeert; revoke erna herordent het effect niet en blokkeert nieuwe inhoudsvrijgave. Verloren ACK vóór duurzaamheid is geen succes; na duurzaamheid alleen reconstrueren, niet nog eens schrijven.

## Concrete slice en meetwijze (DERIVED implementatie)

Eén eigen kalender, één synthetische eigenaar, één exacte CREATE_OWN_EVENT met geprovisioneerde write-grant en exact digestakkoord. Dit bouwt de transactionele commitgrens, geen complete Hannie-provider of accountflow.

De schrijver gebruikt één BEGIN IMMEDIATE-transactie voor authoritative auditsequence, besluit, effect, versie, akkoordverbruik en immutable receiptbinding. Revoke gebruikt dezelfde database en auditsequence. De writer geeft nooit SUCCEEDED: hij wordt na COMMIT abrupt met SIGKILL beëindigd. Een nieuw readerproces opent de database read-only en reconstrueert besluit/effect/receiptbinding. Ontbrekend of afwijkend bewijs geeft RESULT_UNKNOWN/HOLD. Recovery schrijft niets.

Een tijdsample vóór COMMIT heet alleen precommitObservedAt; hij autoriseert niet achteraf de duurzaamheid. De returned decisionAt/effectAt zijn **post-crash readback-upperbounds**, gemeten bij reconstructie van beide gebonden rijen. Zij bewijzen geen exact fsync-tijdstip, betrouwbare ERA-tijd of twee duurzame momenten. SUCCEEDED wordt alleen geretourneerd wanneer volledige readback na de werkelijke crash vóór de gebonden grant/approval-expiry plaatsvindt. Dat is een conservatieve bovengrens: bewijs na expiry kan geen tijdig succes aantonen. Beide returned velden zijn reconstructiemetingen op de ene commit, geen tweede databasetransactie; de originele receiptbinding blijft ongewijzigd. Deze afgeleide meetwijze vraagt onafhankelijke contractreview.

Late durability kan een effect achterlaten waarvoor geen tijdig succes kan worden aangetoond. Dat wordt HOLD met minimale bindingsmetadata, nooit SUCCEEDED, nooit automatisch gewist of opnieuw uitgevoerd. De candidate claimt geen absolute fysieke storage-deadlinegarantie of nul late effecten. Dit expliciete restrisico blijft een acceptatieblocker als de norm tevens eist dat na expiry geen effect mag bestaan.

Alleen de fixture-authority mag provisioning doen; supplied requestvelden of persona's creëren geen rechten. Geen live identiteit/admission, D1, providerdispatch, externe restore-/trust-epoch, integratie, productie, merge of officiële PROOF in deze slice. Lokale tijd/fixturegrant is geen geattesteerde authority.

## Nieuwe controles, geen hergebruik van deny-evidence

Werkelijke SIGKILL vóór COMMIT: geen besluit/effect/consumption/receipt. Werkelijke SIGKILL na COMMIT: alle zes samen zichtbaar na nieuw proces. Revoke-first: nul effect. Commit-first: effect behouden, nieuwe inhoud geweigerd. Verloren ACK vóór duurzaamheid: RESULT_UNKNOWN, read-only recovery blijft leeg. Verloren ACK na duurzaamheid: reconstrueren, één effect/audit/consumption. Echte SQLite-concurrentie: gedeelde ordering. Native WAL-stall vóór duurzaamheid: precommit-sample kan geen tijdig succes dragen. Stale digest/context/generation/approval, receiptcorruptie en replay worden afgewezen. Bron/runtime/run-ID/raw TAP/native traces/hashbinding horen uitsluitend bij deze nieuwe B-candidate.

## Status

SPECIFICATION DRAFT / ACCEPTANCE OPEN. De actuele bouw- en uitvoeringsstatus staat in het afzonderlijke B-evidence-rapport; deze contracttekst verleent geen acceptatie. Onafhankelijke review PENDING. Integratie/productie HOLD. Merge NOT AUTHORIZED. PROOF NOT ISSUED.
