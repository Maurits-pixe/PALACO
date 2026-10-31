# Citadel Bastion — previewcandidate

Last Updated: 2026-10-07

Dit is een afzonderlijke privépreview van de aangeleverde Bastion-interface. De fixturetaken, chat en auditregels zijn lokaal en fictief. De metadata-route is uitsluitend bedoeld voor de launchercontrole.

De aangeleverde `const success = true` en lokale `applyMutation` zijn verwijderd. Bevestigen schrijft niets, consumeert geen ticket en verandert geen taak. De interface rapporteert `STORAGE_EFFECT_DEADLINE_UNSUPPORTED`; dit is een guard, geen D-013-fix. De standaard statische build heeft geen serverroute, database, agenda-provider, login of productiegegevens aangesloten.

Alleen de root-Compose-demo bouwt met `VITE_BASTION_DEMO=true`: een afzonderlijke, alleen-lezen sectie toont ciphertexttaken uit `services/bastion-demo` via dezelfde origin (`GET /api/tasks`). Gebruik **Vernieuw demotaken** na een overdracht uit Aether. Die expliciet lokale API kan uitsluitend demo-enveloppen opslaan; zij heeft geen routes voor afronden, escaleren, verwijderen of bevoegd uitvoeren. De fixturebediening en D-013-blokkering blijven ongewijzigd. Dit is geen aangesloten productie-Bastion-backend. Zie de root-README voor opstarten en wissen van de demodata.

De bron gebruikt Vue 3 en Vite. `npm test` controleert de identity-binding en de default-deny-eigenschap; `npm run build` maakt de statische preview. Lokale dev/preview gebruikt HTTPS op poort 5175 wanneer een wegwerpcertificaat in `certs/` aanwezig is. De statische preview bevat security headers via `public/_headers`.

De volledige achterliggende Citadel-module is niet bewezen door deze preview. De voorgestelde 30-secondenafteltekst is daarom niet als bevoegdheidscontract opgenomen. `npm run test:browser` laadt de gebouwde preview in Edge, controleert de identity-route en headers en bevestigt dat een mutatieklikwflow geen taak verandert.

Voor automatische Vercel-PR-previews: [Web preview deployments](../../docs/operations/Preview-Deployments.md).

Zie [D013-REVIEW.md](D013-REVIEW.md) voor de beoordeling van de later aangeleverde SQLite-backend. Die backend is niet aangesloten.
