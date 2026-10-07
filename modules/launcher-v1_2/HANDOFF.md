# PALACO launcher v1.2 — bronoverdrachtcandidate

Last Updated: 2026-10-07

Dit is een afzonderlijke previewcandidate. ACCEPTATIE / INTEGRATIE / PRODUCTIE: HOLD. De bronoverdracht is geen D-013-fix en geen bewijs dat de drie achterliggende modules operationeel zijn.

## Herkomst

De volledige toevoegingen en de browserharnesscorrectie zijn teruggevonden in de oorspronkelijke taak **Tijdelijke appkoppeling maken**, codingtaak `01a11267-25b7-7591-94a7-521f04dfd065`, werkpad `/workspace/scratch/e7e38f62a674/palaco-launcher-v1_2`. Deze versie is uit de zichtbare bestandswijzigingen hersteld; het oorspronkelijke ZIP-bestand en lockfile zijn niet overgedragen. Het nieuwe lockfile en de lokale testresultaten behoren aan deze candidate. Historische bewijsclaims in README/ACCEPTANCE mogen niet als nieuw uitgevoerde tests worden gelezen.

Wijzigingen voor deze overdracht: expliciete previewmelding, Node native config loading voor Windows, portable OpenSSL-testconfiguratie, browserheadercontrole, lokale beveiligingsheaders en statisch hostingbestand, afzonderlijke standaard gesloten mutatieguard en resultaatmodel. De oorspronkelijke verificatiecontroller is behouden. Geen token- of handtekeningmodel toegevoegd.

## Grenzen

- AETHER, BASTION en 5CRIPTIE zijn catalogusbestemmingen; hun volledige applicatiebron is niet teruggevonden. Fixtures zijn herkenbare testpagina's, geen werkende modules.
- De launcher doet uitsluitend metadata-GET-verzoeken zonder credentials. Metadata met appId/status is geen bewijs van autorisatie of veilige inhoud.
- De statische hosting bevat geen agenda-API, SQL, database, productiedata of secrets. Een HTTP-methodetest op de aparte serverguard bewijst geen integratie met die hosting.
- De standalone guard blokkeert vier prepare/execute-ingangen voor alle methoden met `STORAGE_EFFECT_DEADLINE_UNSUPPORTED`, zonder opslagverbinding of consumption. Alle overige routes geven 404. Er is geen vrijgaveflag.
- `server/client-result.mjs` bewaart eerdere `RESULT_UNKNOWN` en bestaande opaque operationele bindingen in geheugen. Het implementeert geen duurzame receipts, autorisatie of readback en verleent geen rechten.
- PR #38 en diens synthetische SQLite-writepad zijn niet gewijzigd of aangesloten. De herhaling van B12 op diens exacte bron toont een late crash-overlevende mutatie; D-013 blijft onbewezen.
- De gebruikerbijlagen met PostgreSQL NOW(), dertig seconden en UI-revert zijn niet toegepast. Een tijdcontrole vóór COMMIT kan geen tijdige duurzaamheid garanderen. PostgreSQL NOW() is bovendien transactiestarttijd: https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT.
- PR #39 is een bestaande andere PR. Deze overdracht krijgt bij aanmaak een nieuw, door GitHub toegewezen nummer en blijft draft.

## Reproduceren

Node >=22.12; `npm ci`, `npm test`, `npm run build`, `npm run test:tls`, `npm run test:browser`, `npm run test:guard`.

Voor de browsertest moet Playwright Chromium beschikbaar zijn of `PALACO_BROWSER_RUNTIME_CONFIG` verwijzen naar JSON met `executablePath` en `args: []`. De testcontext accepteert alleen tijdelijk de wegwerp-CA; een afzonderlijke browsercontext test weigering zonder die uitzondering. OpenSSL moet beschikbaar zijn. De test installeert geen certificaten in het systeem.

De originele README beschrijft lokale HTTPS-start met eigen certificaten. De aparte guard start met `npm run guard` uitsluitend op loopback. Open deze guard nooit als bewijs van geautoriseerde agenda-uitvoering.

## Tijdelijkheid

Preview is privé en afzonderlijk van bestaande applicaties. Er is nog geen verwijderdatum overeengekomen of automatische verwijdering ingesteld. Bron en bewijs blijven behouden als de preview later wordt verwijderd.
