# HARA — toelatingscontract en synthetisch conformance-model

Datum 2026-11-05. Baseline PR #105 head 90ea5ecbae1a184874b19b999e0d347d6b6963e8. De afgebakende clientadapterreview is afgerond: CA-01 hersteld; geen aanvullende bevestigde fout in de onderzochte adapterpaden. Dit is een eigen AI-review, geen formele onafhankelijke acceptatie. Deze nieuwe slice bouwt een requirements-model voor admission, geen echte authenticatie of accountintegratie.

## Scheiding van verantwoordelijkheden

Clientselectie blijft UNAUTHENTICATED_CONSENT_SELECTION / REQUIRES_OWNER_AUTHENTICATION. Een client kan alle velden namaken; geen van die velden, inclusief selectedAt, digest of checkbox, verleent serverauthority. De server mag actorcontext, grants, policy, klok en challenge-state niet uit een client-JSON als waarheid overnemen.

Nieuwe src/admission.mjs is een pure functie checkAdmissionSnapshot. De enige ondersteunde invoercontext is SYNTHETIC_ADMISSION_SNAPSHOT_V1. Voorafgaande host-verificaties worden uitsluitend als testasserties in de snapshot gemodelleerd. verified=true of timeTrusted=true is in deze module geen credentialverificatie. Het model doet geen database-/netwerk-I/O, geeft geen signature of approval uit en is niet aan execute() gekoppeld.

Zelfs een positieve uitkomst heet alleen SNAPSHOT_REQUIREMENTS_SATISFIED en heeft authorityGranted=false. Zij is geen producttoestemming. Zo kan de inhoud van de admissionvoorwaarden worden getest voordat een echte identity/admissionbron is gekozen of gekoppeld.

## Geteste requirements

De snapshot moet actor owner/tenant/session aan de runtimecontext binden, origin-verificatie aangeven, de juiste kalender/ACL en policy tonen, en een exact actieve CREATE_OWN_EVENT-grant met generatie, profiel en finishAfterExpiry-opt-in bevatten. De hosttijd moet strikt vóór zowel grant- als voorgestelde approval-expiry liggen. Een oude client-selectedAt kan deze controle niet omzeilen.

De challenge moet open en onexpired zijn en context/request/preview binden. De host-confirmatie verwijst naar exact die challenge en preview en bevat beide expliciete keuzes. De clientselectie moet exact overeenkomen. Een gebruikte of verkeerd gebonden challenge wordt afgewezen. Dit toetst aangeleverde snapshottoestand; het implementeert geen atomair challengeverbruik of concurrentiecontrole.

## Nog te implementeren echte serverinterfaces

| Stap | Vereist contract | Bewijs vóór echte integratie |
| --- | --- | --- |
| verifyOwner | Verifieer credential/sessie via echte identitybron; leid owner/tenant/session af uit serververificatie, nooit uit callerclaims | Geldig, verlopen, ingetrokken en vreemd-account credential; geen authenticatie uit actor.verified |
| verifyOrigin | Bind bevestigingsrequest aan dezelfde geauthenticeerde sessie en toegestane browser-origin/anti-forgerycontrole | Cross-origin en cross-session bevestiging geweigerd |
| loadAuthoritativeSnapshot | Laad policy, kalenderrechten, grantgeneratie/-status en betrouwbare tijd uit benoemde bronnen | Stale grant, revoke, tenantwisseling en klok/trustverlies geven geen approval |
| issueChallenge | Maak niet-voorspelbare challenge met context-, request-, profiel-, preview-/risicotekstversie en expiry-binding; bewaar server-side | Bindingwijziging, verlopen of vreemde challenge afgewezen |
| issueExactApproval | Atomair één open challenge verbruiken en één exact gebonden approval vastleggen; idempotente operationId/approvalId; geen succes vóór eigen durabilitybewijs | Echte gelijktijdige bevestigingen, crash vóór/in/na commit, false/lost ACK; één of nul approval, nooit dubbele uitgifte |
| dispatchToCandidate | Gebruik alleen de geverifieerde servercontext en werkelijk uitgegeven approval; behoud onafhankelijke uitvoeringschecks | Revoke/expiry tussen admission en execute wordt opnieuw gecontroleerd; clientselectie wordt niet in een approval omgezet door veldhernoemen |
| restoreAndTimeTrust | Bind trust/restore-epoch aan een bron buiten een terugzetbare snapshot, met benoemd klokprofiel | Teruggezette grants/challenges/approvals worden geen hernieuwde authority; trustverlies HOLD |

Voor issueExactApproval moet de concrete provider/transactiestore nog worden gebonden. Dit document introduceert geen queue, productiecredential, endpoint, migratie of achterdeur naar fixtureprovisioning. Het huidige runtimecontract met één mutatiecommit blijft ongewijzigd. Het schema voor echte challenge/approval-uitgifte en de bijbehorende storagekeuze zijn nog niet vastgesteld of gebouwd.

Een schema ‘CLIENT_SELECTION → OWNER_VERIFIED → EXACT_APPROVAL_DURABLE → EXECUTION_REVALIDATED’ is uitsluitend een specificatie van de gewenste keten. De huidige checker implementeert alleen controle van een synthetische snapshot van de requirements; geen van die daadwerkelijke trustovergangen wordt als uitgevoerd geclaimd.

## Nieuwe uitvoeringsevidence

Run d6c2209e-d63b-4128-92c1-e66027d4a55b, Node v24.19.0 Linux: runtime 24/24 PASS, client 13/13 PASS, admission-snapshot 20/20 PASS. Elke suite heeft eigen TAP, exitcode en counters; alle drie zijn verplicht voor gecombineerde PASS. Verifier reconcilieert alle drie samenvattingen. Bronset 5469f646861021c288ad941996a37147d297fe591219a89f7a263b85b8071d2f vóór/na gelijk; 19 bronhashes en 31 artifacthashes PASS. git diff --check PASS.

A01 toont complete snapshot met authorityGranted=false, geen approval en ongewijzigde fixturestaat. A02–A20 tonen ontbrekende verificatie/origin, vreemde eigenaar/tenant/sessie, verkeerde grantgeneratie, revoke, serverexpiry ondanks vroege clienttijd, gebruikte/verlopen challenge, policy-deny, ontbrekende risico-erkenning, verkeerde challenge/digests, time-trustverlies, ACL en ontbrekende profielopt-in. Per case is fixturestaat vóór/na gelijk. Dit zijn requirements-/side-effectcontrols, geen tests van een echte authenticatieprovider of concurrerende approval-uitgifte. Nieuwe CI wordt aan de gepubliceerde exacte head gebonden; eerdere CI blijft historisch.

## AI-review aan de hand van drie lenzen

TRIAS: het model verleent nooit authority en houdt identiteit/approval-uitgifte buiten een zelfverklaarde snapshot. ORACLE: alle drie suites en ontbrekende provider-/duurzaamheid-/restoretests zijn apart benoemd; geen claims over echte credentials. MENTOR: concrete interfaces geven de volgende implementatieslice een duidelijke plek zonder een authprovider te verzinnen. Eén AI-bouwer; formele onafhankelijke acceptatie PENDING.

Status MODEL IMPLEMENTED / LOCAL 24 RUNTIME + 13 CLIENT + 20 SNAPSHOT CONTROLS PASS / REAL ADMISSION NOT IMPLEMENTED / INTEGRATION HOLD / PRODUCTION HOLD. Volgende overgang: exacte head → eigen matrix-CI → admission-interface-review en binding aan een echte authority-/tijdbron vóór enige echte accountintegratie. Geen merge/deployment/PROOF.
