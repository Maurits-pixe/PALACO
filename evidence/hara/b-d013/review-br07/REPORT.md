# H∆R∆ — BR07 evidence harness · 31 oktober 2026

Resultaat: evidence-runner gebruikt bestandsdescriptors voor test- en compileroutput, rapporteert procesfouten/signals en isolatiemodus, en vereist exact 22 controles zonder FAIL/skip/cancel/todo. Bronhashcontrole vóór/na behouden. Standaard Node-procesisolatie blijft default; `B013_TEST_ISOLATION=none` is expliciet als lokale variant vastgelegd. Candidateworkers blijven afzonderlijke processen.

CI-configuratie voorbereid: Node 24.14.1 en 24.19.0, elk met process en none; artifactnamen onderscheiden alle vier combinaties. CI NOT EXECUTED. Geen remote push, merge of deployment.

## Bewijs

Definitieve positieve run 57116f39-86f2-40df-88c0-5d66f00b902b: Node v24.19.0/Linux, 22/22 PASS, onveranderde bronset b53affe1abd9e022ea7f6396a94285e8e9ff4cbe6d0963e9dac93501441c0f77. SHA-256 van bronset, actuele bronbytes en alle 21 artifacts afzonderlijk met Python gecontroleerd: PASS. git diff --check PASS. Bronset bindt ook README en workflow. Head is baseline, niet een commit van de lokale patch; candidate.patch plus bronhashes identificeren de lokale wijziging.

Negatieve run bce397cd-6ff3-42fc-b179-f42a25bd3f38 op dezelfde bron: standaard process-isolatie toont in deze cloudomgeving één wrappertest. Runner geeft terecht FAIL ondanks de 1/1 wrapper-PASS. Dit is bewijs voor de afwijzing van een onvolledige telling, geen volledige process-mode-verificatie. De onderliggende beperking van geneste testoutput is niet als opgelost geclaimd. Oude onvolledige runs behouden.

## AI-review aan de hand van drie lenzen — dezelfde assistent

TRIAS: geen wijziging aan D-013, authority of mutatiesemantiek in deze slice; BR06-patch blijft afzonderlijk zichtbaar. Defaultisolatie niet stilzwijgend vervangen. ACCEPTANCE HOLD behouden.

ORACLE: positieve en negatieve runs op identieke bronset; ruwe TAP, native/crashtraces, procesmetadata en hashes beschikbaar. Nieuwe CI en onafhankelijke review ontbreken. B12 laat nog een laat effect achter; lokale PASS sluit dat contractprobleem niet.

MENTOR: één reproduceerbaar lokaal commando en expliciete CI-matrix. Exacte testtelling moet bij uitbreiding worden onderhouden. Volgende geldige overgang: deze gebonden candidate naar afzonderlijke review en remote CI; voorbereiding binnen GO. Onafhankelijke reviewer moet de BR06-runtimewijziging en de aangepaste harness beoordelen. Geen zelfstandige acceptatie door deze AI-review.

Status IMPLEMENTED / LOCAL EVIDENCE VERIFIED binnen genoemde Node-/isolatiemodus / CI NOT EXECUTED / INDEPENDENT REVIEW PENDING / ACCEPTANCE, INTEGRATION, PRODUCTION HOLD. Geen PROOF.
