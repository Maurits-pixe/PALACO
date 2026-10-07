# PALACO Hoofdkantoor — Launcher v1.2

**Afzonderlijke herstelcandidate `1.2.0-candidate.1`.** Het pakket bevat een volledige Vue-launcher, productiebundle, vastgelegde dependencies, regressietests en evidence. Lees `REVIEW.md` voor de uitgevoerde controles en hun grenzen. `ACCEPTANCE.md` bevat de gerichte acceptatiebasis.

De launcher controleert modulemetadata en opent de geverifieerde origin. AETHER, BASTION en 5CRIPTIE behouden hun namen en appId. Dit pakket bevat niet de achterliggende versleutelings-, commandocentrum- of monitoringmachines.

## Lokaal starten

Gebruik Node 22.12 of nieuwer; deze candidate is uitgevoerd met Node 24.19.0. De dependencies staan exact gepind in `package.json` en `package-lock.json`.

```bash
npm ci
mkdir certs
mkcert -cert-file certs/localhost.pem -key-file certs/localhost-key.pem localhost 127.0.0.1 ::1
npm run dev
```

Voor deze mkcert-opdracht moeten mkcert en jouw vertrouwde lokale CA al zijn ingericht volgens de [mkcert-handleiding](https://github.com/FiloSottile/mkcert). De uitvoerbestandsnamen komen exact overeen met de configuratie. Er zijn geen private certificaatsleutels meegeleverd of CA's in het systeem geïnstalleerd tijdens deze bouwstap.

Open **https://127.0.0.1:5173**. Dev en preview gebruiken dezelfde vaste poort en uitsluitend HTTPS. Ontbrekende/ongeldige certificaatbestanden of een bezette poort blokkeren de server. Er is geen stille HTTP-fallback.

Een productiebundle bouwen vereist geen lokale certificaten:

```bash
npm run build
```

Een lokale HTTPS-preview van die bundle vereist de hierboven benoemde certificaten:

```bash
npm run preview
```

## Bediening en modulemetadata

1. Vul een exacte origin uit `src/catalog.js` in, bijvoorbeeld `https://localhost:5175` voor BASTION. Geen afsluitende slash, pad, query, fragment of gebruikersgegevens.
2. Kies **Opslaan & verifiëren**. De launcher vraagt `/.well-known/palaco-app.json` op, zonder credentials of redirects.
3. Open de module na **Modulemetadata bevestigd**. De bevestiging geldt maximaal 60 seconden en vervalt bij terugkeer naar de pagina.
4. Tijdens een check kun je **Annuleren**, of de origin wijzigen; een wijziging trekt de oude poging meteen in. Start daarna de nieuwe check.

De module moet HTTP 200 en een JSON-object van maximaal 64 KiB leveren, met stringvelden `appId` en `status`. De appId moet bij de module horen. Voorbeeldmetadata voor BASTION:

```json
{"appId":"bastion","status":"ready"}
```

`ready` is een voorbeeldwaarde, geen opgelegd contract-enum. Een cross-origin module moet een passende `Access-Control-Allow-Origin` voor de launcher teruggeven; voor bovenstaande lokale launcher is dat `https://127.0.0.1:5173`. Een transportfout bewijst niet welke van netwerk, CORS, TLS of redirect de oorzaak was.

De allowlist is ongewijzigd overgenomen uit de aangeleverde v1.1 en is configuratie, geen bewijs van domeineigendom of werkende apps. Er wordt niets automatisch geverifieerd of uit localStorage teruggezet.

## Herstelde grenzen

- Eén private pogingobjectidentiteit en een oplopend BigInt-generatienummer, los van de wallclock.
- Onveranderlijke origin/controller/deadline per poging; ownershipchecks na iedere await en vóór statewijzigingen.
- Eén 5000 ms deadline voor fetch, body, workerparsing en schema-/identiteitsvalidatie. Resultaatacceptatie weigert bij `now >= deadline`, ook als de watchdog later uitvoert.
- JSON-parsing in een afbreekbare worker; timeout/annulering beëindigt de worker. Een limiet van 64 KiB begrenst de geaccepteerde metadata.
- Private monotone vervaldeadline en zelfstandige launchcontrole op de exacte grens. Wallclock kan alleen eerder laten verlopen; focus/visibility/BFCache-terugkeer vereist opnieuw verifiëren.
- Foutcodes per fase, zonder tekstherkenning van browserfouten. Reactieve countdown en cleanup bij echte Vue-unmount.
- Certificaten uitsluitend voor dev/preview; expliciete bestandsnamen en parseerbare key/certificaatcombinatie.

De browser is geen real-time scheduler. Een overbelaste hoofdthread kan timer/statusweergave vertragen. De toetsbare garantie is **geen succes accepteren op of na de deadline**, plus een terminateerbare parseworker; niet beëindiging van alle OS/netwerkactiviteit exact op 5000 ms.

## Reproduceren

Werk voor een nieuwe run in een kopie van het uitgepakte project, zodat het opgenomen bewijs intact blijft. Voer suites achter elkaar uit: de TLS- en browsersuites gebruiken tijdelijk poorten 5173–5176. Er worden uitsluitend lokale testfixtures gestart.

```bash
npm ci
npm test
npm run test:tls
npx playwright install chromium
npm run test:browser
```

De TLS-/browsersuites vereisen OpenSSL en genereren disposable sleutels onder `.test-tmp/`. Ze wijzigen geen trust store en ruimen hun tijdelijke projectkopieën na afloop op. De browsertest duurt onder meer één echte minuut voor de 60-seconden-vervalcontrole. Positieve browserfixtures gebruiken `ignoreHTTPSErrors` uitsluitend binnen hun testcontext; een aparte normale context controleert weigering van de onbekende test-CA. CORS en redirectbeleid blijven ingeschakeld.

In deze omgeving is Chromium 138.0.7204.0 uit `@sparticuz/chromium@138.0.2` gebruikt, omdat de normale Playwright-browserdownload onbruikbaar was. Wie die exacte Linux-bundel wil gebruiken kan die buiten dit project installeren en een runtime-JSON opgeven via `PALACO_BROWSER_RUNTIME_CONFIG`. Dat JSON bevat `executablePath`, `args` en eventueel `bundleVersion`; de uitgevoerde args en executable-hash staan in de browser-evidence. De harness weigert flags die websecurity of globale certificaatcontrole uitschakelen. Een nieuwe run met een andere browser is afzonderlijk bewijs.

De ruwe resultaten krijgen unieke run-ID's en nieuwe JSON-bestanden onder `evidence/`. `MANIFEST.json` bindt alle opgenomen bestanden met SHA-256. `baseline/PALACO-Launcher-v1.1-Review-HOLD.zip` bewaart de oorspronkelijke tegenvoorbeelden; de v1.1-review is niet overschreven.

## Grenzen van de candidate

Een metadataresponse verleent geen authenticatie, autorisatie of gegarandeerde veiligheid. Het volledige oorspronkelijke DRAFT-contract, echte externe modules, mkcert-/OS-trust, andere browsers, CI, onafhankelijke menselijke acceptatie en Site-publicatie zijn geen onderdeel van het uitgevoerde bewijs. De bestaande online launcher en tijdelijke Bastion-ingang blijven buiten dit pakket.

Primaire documentatie: [Vite config](https://vite.dev/config/#conditional-config), [Vite HTTPS](https://vite.dev/config/server-options.html#server-https), [AbortController](https://developer.mozilla.org/en-US/docs/Web/API/AbortController/abort), [Worker termination](https://developer.mozilla.org/en-US/docs/Web/API/Worker/terminate), [monotone tijdmeting](https://developer.mozilla.org/en-US/docs/Web/API/Performance/now), [Vue lifecycle](https://vuejs.org/api/composition-api-lifecycle.html#onunmounted), [Playwright clock](https://playwright.dev/docs/clock).
