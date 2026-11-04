# HARA — niet-uitvoerende toestemmings- en receiptadapter

Datum 2026-11-04. Baseline PR #105 head b9618db2653405a6719f7ddb386577b5b694cfa3. Nieuwe src/client.mjs en tests/client.test.mjs; bestaande runtimeworker, authorityregels en aangenomen deadlineprofiel ongewijzigd. Geen website, DOM-renderer, echte OWNER-login, backend-admission of browserintegratie gebouwd.

## Resultaat

prepareConsent legt één exacte request/context/deadline-snapshot vast, inclusief onvervangbare risico-uitleg: de ene opdracht mag later worden vastgelegd, zonder gegarandeerde maximale vertraging. Beide expliciete keuzes zijn vereist. Previewwijziging en selectie op/na expiry worden geweigerd. recordConsentSelection levert uitsluitend UNAUTHENTICATED_CONSENT_SELECTION / REQUIRES_OWNER_AUTHENTICATION. Dit maakt geen grant, echte approval of authority aan; execute() gebruikt dit record niet. Een toekomstige server moet eigenaar, actuele scope/policy/grants, betrouwbare tijd en exact akkoord zelfstandig authenticeren en controleren.

presentResult controleert structureel het exacte ondersteunde profiel en receiptversie, request/context/event/snapshot-bindingen, tijdmetingen en releasepunt. Onbekende profielen, oude SUCCEEDED-status, extra legacytijdvelden, tegenstrijdige indicatoren en payload bij UNKNOWN/WITHHELD/DENIED worden geweigerd. Alle uitkomsten houden automatische retry uit. Ontbrekende historische tijdgetuige wordt niet voorgesteld als iets dat nieuwe toestemming alleen kan herstellen. Uitvoer is een plain-text presentatiemodel; geen HTML of interpretatie van titels als markup. De decoder bewijst geen authenticiteit of actuele serverrechten en ontsluit geen nieuwe payload.

## Nieuwe verificatie

Run 39c71034-ec32-4771-9bb8-69ba2cb9ac36 op Node v24.19.0 Linux: 24/24 runtimecontrols en 12/12 clientcontrols PASS, nul FAIL/skips/cancellations/todos. Bronset a677cbcb8c4210cb9a34e1baa1e10f6dbce33ad7e192b12ed80b63eb8aaeeb02 vóór/na gelijk. Verifier: 17 bronhashes, 29 artifacthashes PASS; beide TAP-samenvattingen afzonderlijk gereconcilieerd. Clientuitvoer en eigen stderr/TAP zitten in hetzelfde runpakket, met eigen exitcode/counters die voor PASS verplicht zijn.

C01–C04 toetsen exacte preview, risico-uitleg, twee expliciete selecties, geen authority, mutatiebestendigheid en equality-expiry. C05–C08 toetsen onbekende/geblokkeerde uitkomsten, echte nieuwe-workerreceipt, onbekende versies en verkeerde bindingen. C09–C12 toetsen late-readback-uitleg, extra/tegenstrijdige velden, DENIED zonder payload en ontbrekend historisch trustbewijs zonder misleidende toestemmingsroute. C09 gebruikt een structureel gemuteerde tijdreceipt; aanvullend voert N04 de daadwerkelijke native late-WAL-receipt door dezelfde adapter en bevestigt de juiste uitleg. Geen gemuteerde C09-fixture als runtimebewijs gebruikt.

Ontwikkelruns fd493a75-adf0-446d-8069-ab0d0131a375 en ee3ea2ec-9bad-4205-baac-1b557a087f27 behouden hun eerdere eigen bronsets; niet gebruikt voor de finale bron. Oude 24-control- en RV-01-evidence niet vervangen. Nieuwe CI bindt afzonderlijk aan de gepubliceerde head. git diff --check PASS.

## AI-review en grenzen

AI-review aan de hand van drie lenzen: TRIAS scheidt een checkboxselectierecord van eigenaarstoestemming/authority; ORACLE bindt aparte client- en runtimecontrols aan dezelfde nieuwe bronset en noemt de echte versus gemuteerde receipt; MENTOR levert één herbruikbare niet-uitvoerende adapter met begrijpelijke status-/risicotekst zonder automatische retry. Geen formele onafhankelijke reviewer of productieacceptatie.

Status ADAPTER IMPLEMENTED / LOCAL 24 RUNTIME + 12 CLIENT CONTROLS PASS / FORMAL INDEPENDENT ACCEPTANCE PENDING / INTEGRATION HOLD / PRODUCTION HOLD. Authenticated admission, echt toestemmingsscherm, echte tijd en restore-/trust-epoch blijven open. Volgende overgang: exacte head → eigen Node-matrix-CI → afgebakende adapterreview vóór enige browser-/accountintegratie. Geen merge of deployment.
