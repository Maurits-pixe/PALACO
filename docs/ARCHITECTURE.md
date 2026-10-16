# PALACO-CITADEL — architectuur

## Bestaande monorepo

De repository bevat een Rust-workspace onder `crates/`, webpreviews onder
`modules/`, een afzonderlijke `services/rio-accounts` en documentatie/bewijs.
De volgende relatieve symlinks geven de launchstructuur weer zonder bestaande
bronpaden of deploymentconfiguratie te verplaatsen:

```text
apps/
├── neo-launcher -> ../modules/launcher-v1_2
└── bastion-frontend -> ../modules/citadel-bastion-preview
crates/                         # bestaande Rust-workspace
services/
└── rio-accounts/               # bestaande, afzonderlijke service
scripts/start-all.sh            # uitsluitend lokale webpreviews
docs/D-013-PROTOCOL.md
```

`apps/aether-frontend`, `services/aether-engine` en `services/bastion-core`
zijn **beoogde**, niet geleverde componenten. Lege mappen of testfixtures
worden niet als werkende engines gepresenteerd. De bronoverdracht beschrijft
de grenzen in [`HANDOFF.md`](../modules/launcher-v1_2/HANDOFF.md).

## Technologiekeuzes

Rust biedt memory safety zonder garbage collector en voorspelbare prestaties.
De bestaande Cargo-workspace gebruikt Rust 1.90+, edition 2024, en verbiedt
unsafe code via workspace-lints. Dat bewijst op zichzelf geen cryptografische
correctheid. Een AETHER-engine met `ring`, AES-256-GCM en `rusqlite` is een
ontwerpdoel, geen functionaliteit van deze checkout.

Node.js biedt een groot ecosysteem en een geschikt model voor realtime
I/O en sockets. Hier draait Node de Vue/Vite-tooling. Een geïntegreerde
BASTION-service met Socket.IO, opslag en autorisatie is niet aangesloten.
Beide geleverde interfaces gebruiken Vue; er wordt geen React-app meegeleverd.

## NEO: metadata, geen bevoegdheid

De launcher vergelijkt een exacte HTTPS-origin met de module-allowlist in
`modules/launcher-v1_2/src/catalog.js`. Daarna haalt hij
`/.well-known/palaco-app.json` op zonder credentials of redirects:

- HTTP 200, JSON-object, maximaal 64 KiB;
- stringvelden `appId` en `status`, met de verwachte module-identiteit;
- één deadline van 5000 ms voor ophalen, parsen en controleren;
- maximaal 60 seconden geldigheid, met hercontrole na terugkeer naar de pagina.

Een module moet passende CORS-headers aanbieden. Metadata is zelfgerapporteerd:
een passende `appId` bewijst geen domeineigendom, authenticatie, autorisatie,
module-integriteit of veiligheid van de geopende inhoud.

## Lokale uitvoering en grenzen

`scripts/start-all.sh` controleert Node, geïnstalleerde dependencies en lokale
certificaatbestanden en start de twee bestaande Vite-devservers. De configuraties
binden op `127.0.0.1`, met HTTPS en vaste poorten 5173 en 5175. TLS-configuratie
of een bezette poort doet de start mislukken; er is geen HTTP-fallback.
Het script stopt de overige preview wanneer één proces eindigt en ruimt
procesgroepen op bij afsluiten.

De BASTION-preview bevat fictieve taken en schrijft geen mutaties. Een geslaagde
metadata-check opent dus een preview, geen bevoegd commandocentrum.
Zie [D-013](D-013-PROTOCOL.md) voor de nog onbewezen opslaggaranties en
de [module-README](../modules/citadel-bastion-preview/README.md) voor tests.
