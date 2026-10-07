# D-010 — actuele contractdelta bij de deny-candidate

**Status: opdrachtgeversbesluit B geregistreerd; IMPLEMENTATIE OPEN / ACCEPTATIE OPEN / INTEGRATIE HOLD / PRODUCTIE HOLD.** Dit addendum vertaalt het bestaande besluit naar expliciete eisen. Het activeert geen uitvoering en wijzigt geen historische contractbytes, evidence of PROOF.

## Primaire bron en afbakening

Actueel besluit: [Invulwerkstuk, beslislog D-010](https://app.notion.com/p/3ad8207920724cc59999c6bdf9ebcd73), bron laatst gewijzigd 2026-10-04T21:01:15.615Z, gelezen 2026-10-05. [Bouwcontract v0.3](https://app.notion.com/p/3ef29e9a126a819f9fb2c9409e1b3611), hoofdstukken 6–8, bevat de eerdere mutation-COMMIT/effectdeadline. [Reviewpakket](https://app.notion.com/p/3f029e9a126a817ea12aeab5fc4c4d51) legt het verschil vast. Private originele snapshots blijven gebonden aan het ongewijzigde source-manifest.json; dit addendum beweert geen hashgelijkheid met de actuele Notion-pagina.

D-010 kiest optie B: deadline op het **duurzaam gecommitte TACP-autorisatiebesluit**, geen absolute fysieke effectdeadline. Revoke vóór beslissingscommit blokkeert; revoke erna herordent het historische effect niet, maar beperkt latere inhoudsvrijgave. Besluit en effect moeten volgens dit besluit dezelfde transactie delen; de receipt bevat acceptatie- en effecttijd. De gedeelde auditsequence bepaalt de volgorde, niet de wall-clock.

## Harmonisatie van overgangsregels (werkstuk hoofdstuk 9 / bouwcontract hoofdstuk 6)

1. Prepare, persona-review en exact OWNER-akkoord blijven voorvoorwaarden, geen definitieve authority en geen TACP-commit.
2. Een toekomstige B-candidate moet bij TACP actuele context, policy, scope, kalenderrechten, exacte grantgeneratie, expiry, concern, akkoord en bronrevisie binden. Alleen het duurzame beslissingscommit telt voor de beslissingsdeadline.
3. Besluit, agendaeffect, immutable versie, akkoordverbruik, audit en receipt moeten voldoen aan het vastgelegde atomaire transactiemodel. Dit addendum introduceert geen intentqueue, latere providerdispatch of tweede database als stilzwijgend alternatief.
4. Bij onbekende durability of incomplete receiptbinding: RESULT_UNKNOWN / HOLD; geen fictief succes en geen blinde tweede write. Recovery verleent geen nieuwe authority.
5. Het huidige runtimepad blijft uniform STORAGE_EFFECT_DEADLINE_UNSUPPORTED. Positieve B-uitvoering en bovenstaande mutationtransactie zijn NOT IMPLEMENTED / NOT EXECUTED.

## Harmonisatie van intrekking (werkstuk hoofdstuk 16 / bouwcontract hoofdstukken 6–8)

- Revoke en TACP delen één authoritative orderingmodel. Revoke eerst: geen effect; oude grantgeneraties kunnen niet terugkeren door replay of recovery.
- TACP eerst: latere revoke maakt het historische effect niet retroactief ongedaan. Elke nieuwe inhoudsvrijgave controleert de actuele leesrechten opnieuw; geen HANNIE-fallback naar OWNER.
- Receipt bindt decision/effecttijden, commitsequence, actorcontext, grantgeneratie, exact akkoord, proposal-/snapshotdigest en eventrevisie. Tijdstempels alleen bewijzen geen ordering of betrouwbare tijd.
- Restauratie van oude snapshots mag authority niet herstellen; externe restore-/trust-epochbinding blijft OPEN.

## Resterende bewijsgrens — geen definitie stilzwijgend afzwakken

**DERIVED technische bevinding:** een tijdsample of SQL-insert vóór fysieke WAL-durability bewijst geen duurzaam beslissingscommit vóór expiry. Besluit en effect in dezelfde SQLite-transactie worden samen duurzaam zichtbaar; een onderscheid tussen logisch serialization point, tijdmeting en fysieke duurzaamheid moet dus expliciet worden gespecificeerd en getest. Optie B alleen lost de getoonde WAL-stall niet aantoonbaar op.

Nog te sluiten vóór B-implementatieacceptatie: exact meetbaar TACP-/durabilitypunt; betekenis en bron van decisionAt/effectAt; toegestane intervalclaim (geen bewezen maximum); één transactie versus onderscheiden duurzame momenten; revoke-ordering en crash/ACK-recovery. Geen precommit-sample achteraf als duurzaam akkoordtijdstip presenteren. Dit addendum beslist deze open technische bindingen niet namens de opdrachtgever.

## Vereiste nieuwe acceptatie (NOT EXECUTED)

- Duurzame beslissingscommit vóór expiry; late WAL-durability en scheduler-/opslagwait als negatieve controls.
- Revoke vóór/na TACP volgens gedeelde auditsequence, ook bij echte concurrentie en procesuitval.
- Eén atomair besluit/effect, één verbruik van exact akkoord; geen dubbele eventrevisie bij replay of verloren ACK.
- Receipt met twee duidelijk gedefinieerde tijdstempels, volledige semantische binding en zichtbaar restinterval.
- Inhoudsvrijgave na revoke/expiry geweigerd, minimale OWNER-historische uitzondering behouden.
- Onafhankelijke review op nieuwe exact gebonden B-candidate; geen hergebruik van historische v0.3-mutaties of D-012-deny-PASS als B-bewijs.

## Status en triade

TRIAS: besluit B is brongebonden, maar geen release of authority. ORACLE: huidige bewijsreikwijdte blijft deny/freshness; duurzame B-commit ongetest. MENTOR: sluit eerst serialization/durabilitycontract, bouw daarna één afzonderlijke B-candidate. Dit is één AI-assistent met drie reviewlenzen, geen onafhankelijke beoordeling.

D-010: BESLUIT GEREGISTREERD / IMPLEMENTATIE OPEN / ACCEPTATIE OPEN. R1-F01: herstel in deze harnessrevisie; onafhankelijke herreview PENDING. Officiële PALACO PROOF NOT ISSUED. Integratie/productie HOLD; merge en deployment vereisen een afzonderlijke bevoegde beslissing.
