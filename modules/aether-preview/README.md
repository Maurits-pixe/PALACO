# AETHER — lokale previewcandidate

AETHER is een afzonderlijke PALACO-preview op `https://localhost:5174`. De app gebruikt de browser-Web-Crypto-API om bestanden lokaal met AES-GCM-256 te versleutelen; een sleutel wordt met PBKDF2-SHA-256 uit een wachtzin afgeleid. De wachtzin is minimaal 12 en maximaal 1.024 tekens lang en moet vóór encryptie tweemaal overeenkomen. Alle wachtzinvelden worden geleegd wanneer de pagina verborgen raakt of wordt verlaten. Elke versleuteling gebruikt een verse willekeurige salt en nonce. De versleutelde inhoud wordt opgeslagen in IndexedDB van de huidige browser. Bestandsnaam en MIME-type zitten in de versleutelde inhoud. De wachtzin en afgeleide sleutel worden niet opgeslagen; zonder de juiste wachtzin kan AETHER bestanden niet herstellen.

Dit is een geïsoleerde preview, geen productiekluis of beveiligingscertificering. De metadata gebruikt daarom `preview-blocked` en `preview-only`, niet `operational` of `maximum`. Een launcher-metadata-match bewijst alleen de beperkte metadata-identiteit. Het is geen authenticatie, autorisatie of bewijs van veiligheid. De module staat al in de lokale AETHER-originlijst van de launcher; de tijdelijke Vercel-preview-origin wordt niet vertrouwd of automatisch toegestaan.

IndexedDB bewaart versleutelde bytes, maar dit beschermt niet tegen een gecompromitteerde browser of apparaat, verwijdert geen mogelijke browser-/OS-back-ups en biedt geen herstel bij verlies van de wachtzin. Bestandsnamen zijn alleen na ontsleuteling beschikbaar. App-verwijdering en **WIS KLUIS** zijn geen gegarandeerde veilige verwijdering van opslagmedia. Gebruik **Back-up** bij een kluisitem om het versleutelde JSON-envelope te downloaden; importeren voegt een envelope aan de huidige browserkluis toe. Een back-up bevat geen wachtzin of leesbare bestandsnaam, en moet apart en veilig worden bewaard samen met de bijbehorende wachtzin. De browseropslag is lokaal aan het browserprofiel en is geen back-up op zichzelf.

## Lokale checks

Voor de HTTPS-devserver moeten tijdelijke `certs/localhost.pem` en `certs/localhost-key.pem` aanwezig zijn. Die certificaten worden niet meegeleverd of ingecheckt.

```bash
npm ci
npm test
npm run build
npm run test:browser
npm run dev
```

`npm run test:browser` bouwt de app en voert een Chromium-roundtrip uit voor versleuteling, ciphertext-only IndexedDB, back-up import/export, afwijzing van ongeldige back-ups en ontsleuteling. De test controleert ook dat het annuleren van **WIS KLUIS** items intact laat. Installeer zo nodig Chromium met `npx playwright install chromium`; op Linux kan ook `PLAYWRIGHT_CHROMIUM_EXECUTABLE` naar een bestaande Chromium-binary wijzen. De test serveert alleen de lokale build op een tijdelijke loopback HTTP-server; gebruik voor de app zelf de HTTPS-devserver.

De launcher verwacht lokaal `https://localhost:5174/.well-known/palaco-app.json`; de metadata staat alleen CORS-toegang toe voor de lokale launcher-origin `https://127.0.0.1:5173`. De tijdelijke Vercel-preview is geen toegestane launcher-origin. De statische build maakt `dist/`; stel voor een Vercel-preview de root in op `modules/aether-preview`.
