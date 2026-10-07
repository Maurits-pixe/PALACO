# H∆R∆ — Hannie agenda · D-012 candidate

Nieuwe geïsoleerde herbouw **0.3.3-d012.1**, vanuit de Notion-contracten. Voorbereiding, exact akkoord, rechtencontrole en historische recovery zijn beschikbaar. Iedere agenda-uitvoering weigert met **STORAGE_EFFECT_DEADLINE_UNSUPPORTED**. Integratie en productie blijven **HOLD**.

Dit is nieuwe broncode met een eigen bewijsketen. De onvindbare v0.3.x-code en haar schema 301 zijn niet gereconstrueerd. De oude Notion-records zijn niet gewijzigd of als nieuw testbewijs gebruikt. Het nieuwe lokale schema heet **D012-1** en is geen D1- of productiemigratie.

## Contract en grenzen

- Exacte contractcodes: CREATE_OWN_EVENT, MOVE_OWN_EVENT en EDIT_OWN_TEXT. De CREATE/MOVE/EDIT-familie uit de opdracht wordt hiermee gebonden; EDIT_OWN_EVENT is geen extra toegestane actiecode.
- Eén eigen kalender binnen subject/tenant/Citadel/WORLD. Grants binden de sessie, persona-ontvangers, doel, velden, receiptontvangers, kalenderbinding, policyversie, generatie en expiry.
- Exact akkoord gebruikt de SHA-256-proposaldigest. Dit is een inhoudsbinding, geen handtekening of officieel PALACO PROOF.
- Revocation/expiry zijn terminale generaties. Hoogste tijd wordt lokaal duurzaam vastgelegd; klokterugloop weigert. Een extern restore-/trustanker is nog open.
- Inhoudsvrijgave vindt plaats na de wachtende context-, policy- en opslagdependencies, met opnieuw actuele rechten en een nieuwe tijdsample. De geteste callbackgap is de scope; er is geen absolute scheduler-, netwerk- of opslagdeadlineclaim.
- HANNIE krijgt geen OWNER-fallback. Historische recovery vraagt aparte receiptrechten en actuele veldrechten. Alleen de gebonden OWNER-sessie heeft een beperkte historische metadata-uitzondering zonder afspraakinhoud of eventidentiteit.
- Onraad staat duurzaam op het doelobject, ook bij nieuwe verzoeken, actiecodes, persona's of sessies. Herbeoordeling selecteert één exact voorstel; eigenaarakkoord of meerderheid heft de blokkade niet zelfstandig op.
- Conservatieve nieuwe policy: OWNER_DIRECT vraagt een geauthenticeerde OWNER-context. HANNIE levert HARA-voorstellen met review; een hostroute voor een aantoonbare directe eigenaarinstructie is nog niet gebonden.

**D-010 semantiekbesluit: optie B geregistreerd; implementatie en acceptatie OPEN.** De deadline bindt volgens het actuele opdrachtgeversbesluit aan het duurzaam gecommitte TACP-autorisatiebesluit. De oorspronkelijke v0.3-effectdeadline en oude OPEN-labels blijven historische broncontext. Zie [D010-ADDENDUM.md](D010-ADDENDUM.md) voor de actuele contractdelta en resterende bewijsgrens. Deze candidate implementeert optie B niet: de uniforme execute-deny blijft intact, zonder mutatiebody of effectfallback. De vaste execute-functie weigert vóór argumentgetters, context, klok, hooks, databaseverkeer en receipt-replay; runtime-SQL weigert writes naar events, versies, receipts en mutationaudit. AM-R01 is niet als technische oplossing gesloten.

**Harnessrevisie R1-F01 (2026-10-05):** WAL-writerchildren onderdrukken alleen `ExperimentalWarning`; de lege-stderr-assertie blijft bestaan. Andere warningtypes en echte child-errors blijven zichtbaar en worden door een afzonderlijke regressiecontrole bewaakt. De historische R1 op codecommit 428c66e3 blijft behouden; onafhankelijke herreview van deze gewijzigde bronset is PENDING.

## Bronnen en reproduceerbaarheid

Zie contract-map.json en evidence/hara/d012/source-manifest.json. De publieke branch bevat technische afleiding, bronverwijzingen en hashes. De volledige private Notion-snapshots zijn afzonderlijk aan de eigenaar geleverd voor hashcontrole. Bronhashes zijn lokale integriteitsbinding; zij attesteren geen betrouwbare tijd.

De historische FAIL-expectations bestaan als frozen-controls.json en uitvoerbare nieuwe scenario's. De oorspronkelijke testbytes zijn onbeschikbaar. De WAL-calibratie laat uitsluitend een **privileged SQLite-primitivefixture** een effect schrijven na een echte 2400 ms-WAL-stall; een tweede proces observeert de late zichtbaarheid. Dit valideert de gevaaropstelling. De candidate weigert voor dezelfde armed hazard vóór de eerste write. Dat bewijst weigering, geen geslaagde mutatie of sluiting van de effectdeadline.

Historische afspraken, versies en receipts worden alleen via tests/helpers.mjs met een expliciete privileged fixtureverbinding gemaakt. Zij zijn geen candidate-execution of echte eigenaarstoestemming. Tests staan buiten de package-exports. Vertrouwde procescode met directe database- of bronwijzigingsrechten valt buiten deze API-grens.

## Controleren

Vereist: Linux, Node 24.14+ met node:sqlite, gcc en glibc. Geen externe npm-dependencies.

    cd modules/hara/hannie-agenda
    node tools/run-evidence.mjs
    node tools/check-evidence.mjs /absolute/path/to/result.json

De runner schrijft een nieuwe run-ID, UTC-tijden, raw TAP, native/reader/waittraces, bronhashes, runtimeversies en binaryhashes in evidence/hara/d012/runs/. Hij vervangt geen oude run. Voor private broncontrole: geef het uitgepakte brondossier als tweede argument aan check-evidence.mjs; dat dossier behoudt evidence/hara/d012/sources/.

## Status en onafhankelijke review

**BUILT / lokale tests brongebonden na run / INDEPENDENT REVIEW PENDING / INTEGRATION HOLD / PRODUCTION HOLD / NOT DEPLOYED.** PROVEN_WITHIN_SCOPE in een result.json geldt alleen voor de daar werkelijk uitgevoerde lokale controles. Officieel HOOFDKANTOOR-PROOF is **NOT ISSUED**.

Positieve agenda-mutaties, mutation/revoke-commitordering, mutation-ACK/crashherstel, hosted D1, live identiteit, modeladapters en AM-10 widget/ELIXER/Black/Foundation zijn **NOT EXECUTED / NOT INTEGRATED**. Zie REVIEW.md voor de afzonderlijke revieweropdracht.
