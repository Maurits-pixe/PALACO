# Citadel Bastion — previewcandidate

Last Updated: 2026-10-16

Dit is een geïsoleerde preview. Taken zijn fixtures; de SQLite-backend is uitsluitend voor lokaal gebruik op `127.0.0.1`. API- en Socket.IO-requests vanaf origins buiten `https://localhost:5175` en `https://127.0.0.1:5175` worden geweigerd. De lokale Socket.IO-chat, audit en berichtverval worden niet gedeployed en zijn geen beveiligd communicatiekanaal.

Taakmutaties blijven gesloten. Pogingen worden als `MUTATION_BLOCKED_NO_D013_BACKEND` in SQLite geaudit en geven `STORAGE_EFFECT_DEADLINE_UNSUPPORTED` terug; er is geen mutation ticket of route die taken kan wijzigen. Dit is een guard, geen D-013-fix of conformiteitsbewijs. De database en previewbackend bieden geen authenticatie en mogen niet aan een netwerkinterface worden blootgesteld.

De bron gebruikt Vue 3 en Vite. Start de backend met `npm run server` en de HTTPS-preview met `npm run dev` in aparte terminals; de preview proxy’t alleen `/api` en `/socket.io` naar localhost-poort 3005. De backend maakt `.bastion-preview/bastion.db`; die lokale data-directory wordt niet ingecheckt. Berichten met de optie **Vervalt na 30s** worden uit SQLite verwijderd en de verwijdering wordt geaudit. `npm test` test de gesloten UI-grens en backendgedrag; `npm run build` maakt alleen de statische preview.

Lokale dev/preview gebruikt HTTPS op poort 5175 wanneer een wegwerpcertificaat in `certs/` aanwezig is. De statische preview bevat security headers via `public/_headers`; de preview is niet functioneel zonder de afzonderlijk gestarte lokale backend. `npm run test:browser` controleert de identiteit, headers en blokkering van taakmutaties.

Voor automatische Vercel-PR-previews: [Web preview deployments](../../docs/operations/Preview-Deployments.md).

Zie [D013-REVIEW.md](D013-REVIEW.md) voor de reden waarom deze local-only backend niet als D-013-mutatiebackend kan worden gebruikt.
