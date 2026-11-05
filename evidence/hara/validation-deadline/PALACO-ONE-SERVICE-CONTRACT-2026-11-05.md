# PALACO ONE — HARA-servicemedewerker: aansluitcontract v0.1

Datum: 2026-11-05. ENGINEERING DRAFT. Uitvoeringsrichting door opdrachtgever: PALACO ONE; doel: service voor de consumer en onderhoud aan PALACO. Dit is een concreet aansluitontwerp, geen aangesloten host of verleend onderhoudsmandaat.

## Eerste bouwdoorsnede

| Taak | Voorbereiding | Voorwaarde voor effect | Huidige uitvoering |
| --- | --- | --- | --- |
| Consumer: eigen agenda-afspraak maken | Hannie maakt exacte preview en risicotekst voor CREATE_OWN_EVENT | Eigenaar/sessie/tenant, kalender-ACL, actuele grantgeneratie, eenmalige exacte approval, afzonderlijk leesrecht en betrouwbare tijd | Alleen bestaande synthetische kandidaat; echte aansluiting ontbreekt |
| Consumer: bestaande uitvoeringsstatus tonen | Alleen referenties en status reconstrueren | Geen inhoud zonder actueel READ_OWN_EVENT-recht en tijdvertrouwen | Alleen bestaande synthetische kandidaat |
| Onderhoud: bevinding en wijzigingsvoorstel voorbereiden | Benoem repository/service, exacte bronversie, onderzocht bereik, wijziging en verificatieplan | Toegang tot de aangewezen bron binnen bestaande opdracht | Deze bouwsessie kan toegankelijke projectbronnen onderzoeken; geen algemene productcapability |
| Onderhoud: programma muteren of uitrollen | Afzonderlijk beoordeelbare wijziging met doel, effect en herstelplan | Eigen actuele onderhoudsbevoegdheid voor concrete target/action en geldige releasegrens | Geen HARA-onderhoudsexecutor; geen deploy-route toegevoegd |

Consumentenrechten mogen niet worden omgezet in onderhoudsrechten. Een onderhoudsrecht verleent geen toegang tot consumentenagenda's. Het servicepersonage zelf is geen identity provider, grant issuer of tijdautoriteit. Deze taakdoorsnede beperkt de eerste adapter; bredere productambities blijven bestaan.

## Verbindingspakket dat de echte host moet leveren

Onderstaande namen zijn voorgestelde verantwoordelijkheden, geen ontdekte PALACO ONE-API's. Geen URL, HTTP-route of credentialformaat wordt verzonnen.

| Verantwoordelijkheid | Invoer uit onvertrouwde aanvraag | Vereiste serverbron en uitkomst | Bij ontbreken |
| --- | --- | --- | --- |
| Host identificeren | Route-/productkeuze | Exacte PALACO ONE-repository/versie, deployment, exploitant en configuratiecontract | HOST_BINDING_UNRESOLVED / HOLD |
| Principal verifiëren | Credentialtransport volgens echte host | Allowlisted issuer; geverifieerd subject, account/owner, tenant, sessiereferentie/-versie, account- en sessiestatus | AUTHENTICATION_UNAVAILABLE / HOLD |
| Request-origin binden | Bevestigingsrequest | Host-eigen origin/anti-forgerybeleid; dezelfde geverifieerde sessie | ORIGIN_UNVERIFIED / HOLD |
| Taakscope laden | Gevraagde taak en target | Actuele resource-eigenaar/ACL, policyversie, bevoegde grant issuer, grant-ID/-generatie/-status, actie en doelbinding | AUTHORITY_UNAVAILABLE / HOLD |
| Tijd controleren | Geen autoriserende clienttijd | Geaccepteerd ERA-bewijs met bron-/verifierbinding, interval, freshness en trust/restore-epoch | TIME_TRUST_UNAVAILABLE / HOLD |
| Exacte toestemming vastleggen | Selectie van de getoonde aanvraag | Serverchallenge bindt context, request, profiel, preview-/risicoversie en beide keuzes; atomair verbruik plus approval | Geen dispatch |
| Effect uitvoeren | Interne referentie naar uitgegeven approval | Onafhankelijke actuele controle op het beslispunt; audit en effect volgens gebonden contract | Geen automatische retry bij onzekere uitkomst |
| Resultaat vrijgeven | Status-/inhoudsvraag | Nieuwe controle op huidige leesbevoegdheid; historische commit is geen huidig leesrecht | Alleen toegestane status of HOLD |

De intake legt geen wachtwoorden, sessietokens of private keys vast. Alleen bron-, contract- en configuratiereferenties horen in het bindingsdossier. Echte credentialtransporten horen pas bij de geïdentificeerde hostimplementatie.

## Aansluiting op bestaande code

Baseline: [kandidaatcode op 0987818](https://github.com/Maurits-pixe/PALACO/tree/09878183a623b3188a4fec962348c0c06d0ebd1f/modules/hara/hannie-validation-deadline).

- src/client.mjs kan een preview en niet-geauthenticeerde selectie voorbereiden. Die selectie wordt nooit rechtstreeks een approval.
- src/admission.mjs is uitsluitend het SYNTHETIC_ADMISSION_SNAPSHOT_V1-model. actor.verified en timeTrusted blijven testasserties. Deze functie wordt geen echte hostverifier door een andere naam of wrapper.
- src/index.mjs accepteert een lokaal databasepad/context/request en start workers met flock; het is geen netwerkendpoint. Geen browser mag het pad of trustedHarnessEnvironment leveren. De echte host mag niet direct worden doorgelust naar deze export zonder een afzonderlijk ontworpen interne boundary.
- De process-local klok/witness in index.mjs levert geen ERA-bewijs of restore-overschrijdende trust. Een echte adapter vereist expliciete vervanging/binding en nieuwe conformance-evidence voordat integratie kan slagen.
- tests/approval-store*.mjs is fixtureprovisioning, niet de echte approval issuer. Niet importeren in de productroute.
- Een onderhoudsexecutor past niet onder CREATE_OWN_EVENT en krijgt een afzonderlijk contract; geen willekeurige shellopdracht of deploymentactie in agenda-payloads.

Echte hostselectie is dus niet slechts een endpoint invullen: sessie-, grant-, tijd-, transactiestore- en readbackgrenzen moeten gezamenlijk kloppen. De oorspronkelijke D-013-evidence en het huidige validatiedeadlineprofiel blijven onderscheiden.

## Implementatievolgorde na bronidentificatie

1. Lees en pin de concrete PALACO ONE-hostcode/configuratie; leg vast wie principal, tenant en tijd bewijst.
2. Bouw de kleinste principal/origin-adapter op de bestaande hostbibliotheek; geen nieuwe IdP kiezen wanneer de echte host reeds één heeft.
3. Bind resource-ACL, policy, revocation en trust-epoch aan actuele gezaghebbende reads. Stel benodigde snapshot-/transactionele garanties vast.
4. Bind challenge- en approval-uitgifte met de echte store. Werk de onafhankelijke effectcontrole en tijdverificatie uit vóór aansluiting.
5. Test de echte hostgrens met niet-productieaccounts en bewijs onder andere: gespoofte owner/tenant, verlopen/ingetrokken sessie, vreemd origin, grantrotation/revoke na preview, tijdinterval over expiry, restore/trustverlies, replay en gelijktijdige bevestiging.
6. Bewijs dat consumer-toestemming geen onderhoudseffect kan uitvoeren en onderhoudsrechten geen consumerinhoud vrijgeven. Houd statusherstel en onbekend effect vrij van automatische redispatch.

Dit is een geplande acceptatiematrix, NOT EXECUTED. De eerdere 75 synthetische controles bewijzen deze hostgrens niet.

## Bronnen en huidige open overgang

Het [ACCOUNT-1/IIP-1/AAP-1/AIB-1-contract](https://www.notion.so/31b8b4a45c26440ea14c82e35940877b) is v0.1 DRAFT, operationele gates open. Het maakt account, identiteit, authority en execution expliciet afzonderlijk. Keycloak is er voorkeurskandidaat, geen bewezen PALACO ONE-deployment of automatische providerkeuze.

Het [HARA-bronbindingsdossier](AUTHORITY-TIME-BINDING-2026-11-05.md) bevat de eerder onderzochte BOOK-1-, INDUSTRIE-, RIO- en ERA-bronnen. Aanvullend zijn PALACO-ONE, PALACO_ONE en PALACO ONE uitvoering gezocht in beschikbare Notion/GitHub-bronnen en bestaande lokale projectbronnen. Geen eenduidige hostbinding vastgesteld; dekking is begrensd, geen bewijs van afwezigheid. De brede connectorzoekfunctie is niet beschikbaar.

Eén concrete URL, repository of bestandslocatie voor PALACO ONE is opgevraagd. De naam als uitvoeringsrichting staat vast; de operationele bron blijft onbekend. De afhankelijke runtimeaansluiting wacht op die referentie. Dit document maakt het resterende werk concreet zonder een fictieve authenticatie- of tijddienst toe te voegen.

Eigen AI-review: TRIAS scheidt consumenten- en onderhoudsmandaat; ORACLE benoemt exact welke code synthetisch is en welke hosttests niet zijn uitgevoerd; MENTOR beperkt de eerste echte aansluiting tot bestaande hostinterfaces. Geen onafhankelijke acceptatie.

STATUS: AANSLUITCONTRACT UITGEWERKT / PALACO ONE HOST NIET GEBONDEN / ECHTE ADAPTER NIET GEÏMPLEMENTEERD / PRODUCTIE HOLD. Volgende geldige overgang: concrete PALACO ONE-bron → gepinde interface-analyse → eerste echte principal/origin-adapter. Geen merge, deployment of PROOF.
