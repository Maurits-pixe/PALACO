# D-012 — onafhankelijke review

Bouwer: één coding-assistent. Een zelfcontrole door de bouwer is geen onafhankelijke review. Revieweridentiteit, onafhankelijkheid en acceptatiebesluit blijven PENDING.

1. Selecteer de exacte gepubliceerde branch-head en bewaar repository, head, base, workflowblob en eigen UTC/run-ID. Vergelijk de sourceHashes van de aangewezen lokale run; de evidencecommit mag de geteste code niet hebben veranderd.
2. Hertoets het afzonderlijke private brondossier tegen source-manifest.json; vergelijk Notion-contract v0.2/v0.3 en D-011/D-012 met contract-map.json en de code. Oud historisch evidence is geen nieuw bewijs.
3. Draai run-evidence.mjs zelf in een afzonderlijke omgeving. Bewaar eigen runtime/binaryhashes, raw TAP en native-/readertraces. Hashgelijkheid alleen is geen acceptance.
4. Beoordeel de uniforme deny-route: direct import/constructie, package/factory, callerflags, getters, borrowed methods en subclasses; inspecteer exports en runtime-effecttable-authorizer.
5. Controleer de WAL-calibratie en twee TIME-cases. De calibratie moet echt één 2400 ms-stall en late zichtbaarheid in een tweede proces laten zien. De candidate moet vóór dat gevaar weigeren, zonder events, versies, receipts, consumption of concerns te veranderen. PASS sluit AM-R01 niet.
6. Controleer READ-I01, RECOVER-I01 en READ-I02 plus prepare/revise, opslagwait, echte writerlock, regrant en positieve field-/receiptcases. Na expiry geen HANNIE-inhoud of receiptidentiteit; OWNER-uitzondering uitsluitend minimale historische metadata.
7. Beoordeel exacte digests, consentgeneraties, klokterugloop/herstart, concernrevision en geselecteerde herreview, corruptie van iedere receiptbinding, historische versus actuele versies en privacy van auditmetadata.
8. Beoordeel de expliciet DERIVED conservatieve policies. Zij mogen geen stilzwijgende canon- of autorisatieclaim worden.

## Invulrecord

- Revieweridentity: PENDING
- Onafhankelijkheid van de bouwer: PENDING
- Exact reviewobject / head / base / bronhash: PENDING
- Eigen runtime / run-ID / logs / artifacthashes: NOT EXECUTED
- Bevindingen en dissent: PENDING
- Beperkt oordeel over geteste code: PENDING
- D-010: optie B geregistreerd; normatieve delta in D010-ADDENDUM.md; implementatie en acceptatie OPEN. Deze candidate weigert nog alle mutaties.
- Integratie / productie / merge / deployment: HOLD; afzonderlijke bevoegde beslissing vereist

Deze reviewopdracht kent geen authority toe en benadert geen reviewer. Volgende geldige overgang: exacte candidate → onafhankelijke review met eigen evidence.

## Herreviewdelta R1-F01 / D-010 (2026-10-05)

Het bestaande Notion AI R1-record blijft historische evidence op codecommit 428c66e3. Dit is geen nieuwe onafhankelijke review. Selecteer de nieuwe gepubliceerde head en sourceSetSha256; hergebruik de oude 76/76 niet als bewijs voor deze revisie.

- Controleer R1-F01 op standaardrun én tests/fixtures/experimental-warning.cjs via NODE_OPTIONS; behoud de strict-stderr-foutdetectie. De nieuwe R1-F01-controle moet aantonen dat niet-experimentele warnings en echte errors zichtbaar blijven.
- Vergelijk D010-ADDENDUM.md met het actuele D-010-besluit. Optie B is geregistreerd, maar positieve mutaties/TACP zijn NOT IMPLEMENTED / NOT EXECUTED. Voorafgaande tijdsample, prepare of OWNER-akkoord zijn geen duurzame TACP-commit.
- Leg een exact serialization/durability-contract vast voordat een nieuwe positieve candidate wordt geaccepteerd; een SQL-insert vóór WAL-durability garandeert geen beslissingscommit vóór expiry.
- Behoud de frozen effectdeadline-controls als historische hazard/deny-controls; herlabel ze niet tot bewijs van B-semantiek.
