# H∆R∆ — BR09 evidence consistency · 31 oktober 2026

Nieuwe slice: afzonderlijke check-evidence.mjs valideert complete actuele broninventaris, bronsethash, runner/result-binding, procesuitkomsten, verplichte crashtraces, alle artifacthashes en ruwe TAP-tellingen. Controle vereist exact 22 geslaagde runtimecontroles. Symlinks en run-path traversal worden afgewezen. CI voert de controle en zeven gerichte probes uit op alle vier matrixcombinaties.

Lokale definitieve run 985b1f88-adc1-4460-8325-58b435c01ad2: 22/22 PASS, expliciete isolation none, Node v24.19.0/Linux. Bronset 862c5275074d0326fe90281b00d2a12426a27bd2f75c05912be1fd0cc5b479ad vóór/na gelijk. Afzonderlijke checker: PASS, 21 artifacts. Probes: 7/7 PASS; één geldig pakket en zes negatieve fixtures. Inclusief B12-verwijdering uit zowel bestandenset als manifest, zodat een kale consistente manifestlijst niet volstaat. Disposable kopieën verwijderd. Eerste ontwikkelrun 63f70449-2ae1-495f-8eed-10e709b6f636 behouden als eigen eerdere bron.

Bestaande PR #95 head b45c3c5a8c99dbf420de6bd51d425198a988dad2 heeft negen workflows SUCCESS, waaronder Hannie viermaal 22/22 op beide Nodeversies en isolatiemodi. Dat is historisch bewijs voor die head. Nieuwe BR09-head vereist eigen CI.

AI-review aan de hand van drie lenzen, dezelfde assistent:
- TRIAS: geen wijziging aan runtime-authority of D-013; eigen consistentiecontrole verleent geen acceptatie. Oude candidate/evidence intact in geschiedenis.
- ORACLE: nieuwe 22 runtimecontroles en zeven bewijsprobes, alle daadwerkelijk uitgevoerd. Checker verifieert tegen de actuele checkout; volledige vervanging van vertrouwde bron én evidence valt buiten de claim. Geen oorsprongsattestatie of onafhankelijk reviewerbewijs.
- MENTOR: reviewer krijgt één controlecommando, verplichte B12-tegenevidence en concrete foutcodes. CI moet op de nieuwe bron binden; onafhankelijke review blijft nodig.

Status IMPLEMENTED / LOCAL CONTROLS PASS / NEW CI PENDING / INDEPENDENT REVIEW PENDING / ACCEPTANCE, INTEGRATION, PRODUCTION HOLD. Late effecten blijven mogelijk; geen merge, deployment, activatie of PROOF. Volgende geldige overgang: nieuwe exacte candidate naar CI en afzonderlijke review; push/PR-update binnen eerder verleende toestemming.
