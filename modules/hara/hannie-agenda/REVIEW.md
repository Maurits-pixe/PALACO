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
- D-010 / effectdeadline: OPEN; geen semantiekbesluit
- Integratie / productie / merge / deployment: HOLD; afzonderlijke bevoegde beslissing vereist

Deze reviewopdracht kent geen authority toe en benadert geen reviewer. Volgende geldige overgang: exacte candidate → onafhankelijke review met eigen evidence.
