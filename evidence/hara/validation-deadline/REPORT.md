# HARA / Hannie — nieuwe validation-deadline candidate v0.1

Datum 2026-11-04. Afzonderlijke synthetische candidate, module modules/hara/hannie-validation-deadline. Geen wijziging van modules/hara/hannie-b-d013/src, het oude contract of frozen evidence. Bedoelde reviewbasis: PR #98 head cf0626fda6841a265e430d91efe29cecdf3821b8; nieuwe branch/PR afzonderlijk en gestapeld op die reviewbranch, geen integratie naar main.

## Besluitbinding

De opdrachtgever antwoordde ‘GO, BOUW VERDER’ op de expliciete vraag om het exacte gewijzigde contractvoorstel vast te stellen als basis voor een nieuwe synthetische candidate. decision.json bindt de goedgekeurde voorstelcommit, inhoud-SHA256, profiel, vraag, antwoord en bevoegdheidsscope. Dit is een herleidbaar gespreksrecord, geen ondertekend credential of officiële registratie. De bestaande D-010/D-013-norm wordt voor dit expliciet aangenomen profiel opgevolgd; oude bronnen en B12-evidence blijven als historische norm/bewijs intact. Geen impliciete goedkeuring voor merge, productie, providers of PROOF.

## Werkelijk gebouwd

Eén nieuwe SQLite CREATE_OWN_EVENT-transactie met exact profieldigest, opt-in op request/grant/approval, strikte laatste validatie vóór beide expiries, besluit/effect/versie/akkoordverbruik/receipt/audit atomair. Dezelfde transactie mag na expiry duurzaam worden. Geen maximale latency geclaimd. validatedAt is PRECOMMIT_VALIDATION_OBSERVATION; nooit decisionAt als duurzaam tijdstip.

Echte SIGKILL na COMMIT en een afzonderlijke read-only worker reconstrueren. Geen succes uit ACK, geen blinde tweede write. Nieuwe status COMMITTED vereist exact nieuw receiptprofiel, actuele aparte READ_OWN_EVENT-authority en geen duurzame write-grantrevoke. Controle bij de locked worker-IPC-vrijgave; geen consumer-/netwerkgarantie. Oude requestvormen worden geweigerd. Geen productclient of UI gebouwd.

Read grants zijn afzonderlijk provisioned, gescoped en revocable. Oude schrijfgrants, verlopen leesrechten of eigenaarfallback geven geen payload. Een oorspronkelijke live-supervisorgetuige bindt de exacte validatietijd. Zonder die getuige bij nieuw supervisorproces: inhoud achterhouden. Restore-/trust-epoch en echte ERA/admissionauthority blijven OPEN.

## Nieuwe uitvoeringsevidence

Finale lokale run 3310a946-4c89-4fa2-b9d0-d6db2f22a23d: Node v24.19.0 Linux, 23/23 controles PASS, 0 FAIL/skipped/cancelled/todo. Bronset 9a337ce4f7c6eeb47a740d6fd1d3964772d4a282add778e6c23cf03bf983ef43 vóór/na identiek. Eigen verifier rekent 15 bronhashes en 26 artifacthashes opnieuw uit: PASS. Verifier-tampercontrols: gewijzigde TAP, ontbrekende bron, foutieve D-013-conformanceclaim en extra artifact alle werkelijk afgewezen. verification-controls.json bewaart resultaten. git diff --check PASS.

Drie eerdere 19/23-controls-ontwikkelruns blijven afzonderlijk bewaard met eigen bronsets; hun PASS wordt niet opgevoerd als bewijs voor de finale bron. Geen historische deny-, B12- of D-013-PASS hergebruikt. De native fixturebron is gekopieerd en van afzonderlijke VD_-variabelen voorzien; injector opnieuw gecompileerd en uitgevoerd.

N04: native WAL-write start vóór expiry en hervat erna. De nieuwe candidate reconstrueert één laat effect als COMMITTED met actuele onafhankelijke leesauthority, validatedAt vóór expiry, observedAfterExpiry=true, exactDurableAt=UNKNOWN en deadlineSatisfied=VALIDATION_DEADLINE_ONLY. Het bewijs vermeldt d013Conformance=false. B12 onder D-013 blijft dus niet-conform; het nieuwe owner-approved profiel heeft bewust een andere norm.

N09 bewaart revokeRequestedAt binnen het gemeten native stallinterval en bewijst dat de revoke pas na de decisioncommit geordend wordt. Nieuwe inhoud daarna geweigerd. N16 bewaart een writer-API-fout na echte commit; supervisor houdt het resultaat zonder tijdgetuige achter en replay schrijft niet opnieuw. De vier extra controls controleren leesscope, audit-/JSON-corruptie, echte duplicate-concurrentie en de strikte gelijkheidsgrens.

## Acceptatiereikwijdte en gaten

N01–N16 zijn als contractgerichte synthetische controls uitgevoerd, plus N17–N23. Dit sluit niet alle bredere acceptatie-eisen:

- N13 dekt nieuw-supervisor fail-closed en N19 monotone leesexpiry bij klokterugloop; volledige restore-/trust-epochbinding is NIET GEBOUWD.
- N15 dekt afwijzen van oud requestprotocol en onderscheiden receiptvelden; een echt oud web-/mobielclientpad is NIET GEÏNTEGREERD.
- Echte identiteit, tijdattestatie, OWNER-toestemmings-UI, policy service, providers/D1 en operationele admission zijn NIET GEBOUWD.
- De gevalideerde klok is een synthetisch live-supervisor monotone/wall-floor-profiel. Geen productautoriteit uit een lokale klok of testfixture afgeleid.
- Nieuwe CI op beide Node-versies wordt afzonderlijk aan de gepubliceerde candidatehead gebonden. Geen oude CI als vervanging.

## AI-review aan de hand van drie lenzen

TRIAS: exacte ownergoedkeuring beperkt tot deze nieuwe synthetische scope; geen oude grants/clients stilzwijgend geconverteerd; productie/integratie HOLD. ORACLE: nieuwe echte crashes/WAL/ordering-evidence, eigen bronsets en negatieve verifiercontrols; ontbrekende restore-, client- en authoritybewijzen expliciet. MENTOR: aparte module en gestapelde review-PR houden nieuwe semantiek reviewbaar zonder oude bewijsclaims te overschrijven. Eén AI-bouwer, formele onafhankelijke acceptatie PENDING; geen dissent dat synthetische controls productieacceptatie zouden vervangen.

Status IMPLEMENTED / LOCAL CONTROLS 23/23 PASS / SCOPED SOURCE-ARTIFACT VERIFICATION PASS / FORMAL INDEPENDENT ACCEPTANCE PENDING / INTEGRATION HOLD / PRODUCTION HOLD / PROOF NOT ISSUED. Volgende geldige overgang: nieuwe exacte head → eigen Node-matrix/CI → afzonderlijke review van het nieuwe profiel en de expliciet resterende gates. Geen merge of deployment uitgevoerd/geautoriseerd.
