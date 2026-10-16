# PALACO-CITADEL — architectuur

## Bestaande monorepo

De repository bevat een Rust-workspace onder `crates/`, webpreviews onder
`modules/`, een React-interface onder `apps/aether-frontend`, de Rust-service
`services/aether-engine`, een afzonderlijke `services/rio-accounts` en documentatie/bewijs.
De volgende relatieve symlinks geven de launchstructuur weer zonder bestaande
bronpaden of deploymentconfiguratie te verplaatsen:

```text
apps/
├── neo-launcher -> ../modules/launcher-v1_2
├── aether-frontend/             # React, The Silent Engine
└── bastion-frontend -> ../modules/citadel-bastion-preview
crates/                         # bestaande Rust-workspace
services/
├── aether-engine/              # zelfstandige Rust-service
└── rio-accounts/               # bestaande, afzonderlijke service
scripts/start-all.sh            # lokale interfaces en AETHER-API
docs/D-013-PROTOCOL.md
```

`services/bastion-core` is een **beoogde**, niet geleverde component.
Lege mappen of testfixtures worden niet als werkende engines gepresenteerd.
De oorspronkelijke bronoverdracht beschrijft de historische grenzen in
[`HANDOFF.md`](../modules/launcher-v1_2/HANDOFF.md); AETHER is hier nieuw
toegevoegd, niet als teruggevonden oude bron voorgesteld.

## Technologiekeuzes

Rust biedt memory safety zonder garbage collector en voorspelbare prestaties.
De bestaande Cargo-workspace gebruikt Rust 1.90+, edition 2024, en verbiedt
unsafe code via workspace-lints. Dat bewijst op zichzelf geen cryptografische
correctheid. AETHER gebruikt `ring` voor AES-256-GCM en `rusqlite` voor
versleutelde vaultrecords. De service is een zelfstandige Cargo-workspace,
zodat de dependencygrenzen van de bestaande Foundation-crates niet veranderen.

Node.js biedt een groot ecosysteem en een geschikt model voor realtime
I/O en sockets. Hier draait Node de Vue/Vite-tooling. Een geïntegreerde
BASTION-service met Socket.IO, opslag en autorisatie is niet aangesloten.
NEO en BASTION gebruiken Vue; AETHER gebruikt React.

## AETHER: The Silent Engine

De HTTPS-interface op poort 5174 stuurt een aanvraag via een same-origin
Vite-proxy naar de HTTP-API op `127.0.0.1:3006`. De API vereist een
afzonderlijk bearer-token en controleert browser-origins; dit is geen
multi-user-identiteits- of bevoegdhedenplatform.

De masterkey komt uitsluitend uit serverconfiguratie (`AETHER_MASTER_KEY`);
een ontbrekende of ongeldige sleutel blokkeert de start. `AETHER_API_TOKEN`
is een afzonderlijk geheim dat de gebruiker tijdens de browsersessie invoert.
Geen sleutel/token wordt in de frontendbundle ingebouwd.

De service genereert een recordidentiteit en een nonce en slaat alleen
ciphertext met nonce en metadata op. Een succesresponse volgt pas na opslag.
Er is geen decryptie-endpoint of geïntegreerd sleutelherstel; verlies van de
masterkey betekent verlies van toegang tot de opgeslagen gegevens.

De interface is monochroom en toont uitsluitend requeststatus. Er zijn geen
nep-logs, tijdgestuurde percentages of vertraagde succesanimaties. Bij een
verloren response kan de uitkomst onbekend zijn; dit wordt niet als rollback
gepresenteerd.

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

`scripts/start-all.sh` controleert Node, Cargo, vereiste secrets, geïnstalleerde
dependencies en lokale certificaatbestanden en start drie Vite-devservers en
de Rust-API. De interfaces binden op `127.0.0.1`, met HTTPS en vaste poorten
5173, 5174 en 5175. TLS-configuratie
of een bezette poort doet de start mislukken; er is geen HTTP-fallback.
Het script stopt de overige componenten wanneer één proces eindigt en ruimt
procesgroepen op bij afsluiten.

De BASTION-preview bevat fictieve taken en schrijft geen mutaties. Een geslaagde
metadata-check opent dus een preview, geen bevoegd commandocentrum.
Zie [D-013](D-013-PROTOCOL.md) voor de nog onbewezen opslaggaranties en
de [module-README](../modules/citadel-bastion-preview/README.md) voor tests.
