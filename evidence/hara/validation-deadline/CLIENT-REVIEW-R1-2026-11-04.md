# HARA — clientadapterreview R1

Reviewbasis: PR #105 head f97988569704727ac50176cbbf041ce06e0e4fdf, gestapeld op cf0626fda6841a265e430d91efe29cecdf3821b8. Alleen clientprotocol, regressie en bewijsverificatie gewijzigd; runtimeworker, authorityregels, het aangenomen deadlineprofiel en oude D-013-code onveranderd.

## Bevestigde bevinding CA-01

presentResult accepteerde COMMITTED_RESULT_WITHHELD met juist profiel/operationId, maar zonder positieve gehele auditSequence. Daardoor kon een onvolledig antwoord als ‘Vastgelegde uitkomst’ verschijnen. Dit creëerde geen grant of payload, maar was een te sterke statusclaim voor een onvolledige protocolbinding. De echte runtime levert de sequence wel; de decoder moet die ook verplicht controleren.

Nieuwe C13 gebruikt eerst een werkelijk door de synthetic runtime teruggegeven withheld-resultaat als positieve controle, en verwijdert/verandert daarna auditSequence: ontbrekend, 0, string en fractie. Baseline-run 5256a8e7-bdd7-4a8c-98e8-f8ff0eb44dac toont 24/24 runtime PASS maar 12/13 client PASS met één echte FAIL (Missing expected exception). Raw TAP en bronhashes blijven behouden.

Herstel: WITHHELD vereist naast profiel en exacte operationId een positive safe integer auditSequence. Ontbrekende/verkeerd getypeerde sequences geven RESULT_BINDING_MISMATCH. Bestaande synthetische statusfixtures C05/C12 zijn aangevuld met de sequence die echte serverresultaten al bevatten. Geen signature- of authenticiteitsgarantie geclaimd: een structureel juiste sequence bewijst niet dat een externe afzender betrouwbaar is.

## Uitvoering en bewijs

Finale lokale run 9f5efa7e-8beb-47fa-9499-eac13c631a9d: Node v24.19.0 Linux; 24/24 runtimecontrols en 13/13 clientcontrols PASS; geen fail/skip/cancel/todo. Bronset 5efca51dc5a325b20ab63e879c5bcfaa997d0b8f68d0304307d9995f284b7d16 vóór/na gelijk. Verifier PASS: 17 bronhashes, 29 artifacthashes en beide TAP-samenvattingen gereconcilieerd. Ontwikkel-PASS fe960808-9a42-4ecd-ad3d-ee1f308c4b54 hoort bij een eerdere bronset en vervangt deze finale run niet. Nieuwe CI afzonderlijk aan de gepubliceerde herstelhead te binden. git diff --check PASS.

## AI-review aan de hand van drie lenzen

TRIAS: presentatielaag blijft niet-uitvoerend, selectie blijft unauthenticated en gaat niet naar execute(); geen nieuwe authority of contractwijziging. ORACLE: CA-01 bevestigd met nieuwe FAIL en exacte runtimepositieve controle, daarna nieuwe PASS zonder historische evidence te vervangen. MENTOR: weiger de te sterke statusclaim bij incomplete protocolbinding; geen browser/auth-integratie suggereren. Eén AI-bouwer, geen formeel onafhankelijke reviewer.

Status CA-01 LOCALLY RESOLVED / LOCAL CONTROLS PASS / FORMAL INDEPENDENT ACCEPTANCE PENDING. Echte OWNER-auth/admission, echte tijd, browserintegratie en restore-/trust-epoch blijven open. Integratie/productie HOLD. Volgende overgang: exacte herstelhead → eigen Node-matrix-CI → afgebakende review vóór enige echte account-/browserintegratie. Geen merge/deployment/PROOF.
