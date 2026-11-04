# HARA / Hannie — D-013 runtimebeslisdossier

Datum: 2026-11-04. Status: DERIVED REVIEW / PROPOSAL, geen nieuw canonbesluit. Werkobject: PR #98 head 99794e0d994ca07e1f0dd17bfdbcc7ee4b1d5d1d, module modules/hara/hannie-b-d013. Dit dossier sluit de analyse van de bekende runtimeblokkade; het verruimt de harness-PR niet met een runtimewijziging.

## Gebruikersuitkomst en invariant

Hannie mag een exact goedgekeurde eigen agenda-afspraak uitvoeren, maar mag een te laat duurzaam geworden autorisatiebesluit niet als geldig tijdig besluit presenteren. D-013 bepaalt de crash-overlevende SQLite-commit van besluit en effect in één transactie als TACP. Deadline gehaald uitsluitend als deze commit vóór expiry is bereikt. Een precommit-tijdsample of ACK vervangt dit niet.

CANONICAL bron: [D-013, opdrachtgeverbesluit 2026-10-05](https://app.notion.com/p/8a4f35ebe743499088178364ec04c58d), op 4 november opnieuw gelezen. De historische implementatiestatus in die pagina is geen actuele repo-status. Repo-contract: modules/hara/hannie-b-d013/CONTRACT.md. Behoud van deadline, één transactie, revoke-ordering, read-only recovery en zichtbare onzekerheid is het uitgangspunt.

## Wat B12 werkelijk toont

Reproduceerbare bron: evidence/hara/b-d013/runs/ee6c89c9-9804-463e-ad93-6f1c7c034b3f/B12.json; eigen result.json en tests.tap in dezelfde run. Modulebronset bc7b8b499367efc9187813acab1ac49a0e3519a40528474bf8b6ff1b2e47d75c.

| Waarneming | Waarde |
| --- | --- |
| Native WAL-wacht begint | 1793782479898 ms Unix-tijd |
| precommitObservedAt | 1793782479899 ms |
| Grant/approval expiry | 1793782480314 ms |
| Native WAL-wacht eindigt | 1793782480799 ms |
| Eind wacht minus expiry | 485 ms |
| Hersteluitkomst | COMMITTED_RESULT_WITHHELD / DEADLINE_NOT_PROVEN |
| Laat effect | lateEffectExists = true |
| Tijdig succes geaccepteerd | false |
| Inhoud/receipt vrijgegeven | nee |

De injector wacht vóór de onderliggende pwrite; de 485 ms is de waargenomen overschrijding bij hervatting van die write. Het is geen exacte fsync- of commitlatency. De test reconstrueert na echte SIGKILL het achtergebleven besluit/effect. Readback-bovengrenzen zijn geen exacte duurzaamheidsmomenten. Lokale wall-clock/native traces zijn geen ERA-attestatie.

DERIVED conclusie: geen foutieve SUCCEEDED of inhoudsvrijgave in dit scenario, maar wel een te laat duurzaam effect. De geteste route voldoet daarmee niet algemeen aan de deadline-eis van D-013. De PASS van B12 betekent dat het tegenbewijs correct wordt herkend en bewaard; het betekent niet dat het ongewenste effect afwezig is.

## Waarom eenvoudige reparaties de grens niet sluiten

| Voorstel | Resterend probleem |
| --- | --- |
| Extra expiry-check direct vóór COMMIT | Stall kan na de check optreden; B12 blijft relevant |
| Ruimere timeout of veiligheidsmarge | Geen onderbouwde absolute storage-bovengrens; geen deadlinebewijs |
| Watchdog/SIGKILL op expiry | Scheduling, in-flight write en crash recovery kunnen al geschreven commitdata niet als afwezig bewijzen |
| ACK als autorisatiemoment nemen | Strijdig met D-013; false/lost ACK zijn afzonderlijk getest |
| Na expiry effect terugdraaien | Tweede mutatie; maakt historisch effect niet ongedaan; nieuwe authority nodig, geen stille cleanup |
| Alleen succes/inhoud onthouden | Huidig gedrag; voorkomt vrijgave maar verwijdert het late effect niet |
| Ander databaseproduct kiezen | Op zichzelf geen bewijs: eigen durability/deadline-/crash-/revoke-contract en tests nodig |

Dit is geen bewijs dat elke denkbare storagearchitectuur onmogelijk is. Het begrenst uitsluitend wat met de huidige route en evidence mag worden geclaimd.

## Geldige vervolgroutes

### Route A — D-013 behouden (aanbevolen canonbehoud)

Geen runtimevrijgave van deze SQLite-candidate. Onderzoek een afzonderlijke storagecandidate uitsluitend met een aantoonbaar contract voor deadlinehandhaving op het duurzame commitpunt. Uitvoerbaar technisch onderzoek mag binnen de bestaande bouwscope; gevonden capability verleent geen authority.

Vereiste oplevering vóór positieve acceptatie:

1. Exacte definitie van durability en deadlinebron, inclusief klokfouten en grensgelijkheid (commit op expiry is niet tijdig).
2. Aantoonbaar mechanisme waardoor een na expiry ongeldige transactie niet alsnog als geldig besluit/effect kan worden gereconstrueerd; geen precommit-sample als vervanging.
3. Werkelijke crashes vóór/in/na commit; stalls over expiry; false/lost ACK; read-only recovery zonder nieuwe write.
4. Gemeenschappelijke ordering voor revoke en commit, met revoke-first geen effect en commit-first behoud van historie plus blokkade van nieuwe inhoudsvrijgave.
5. Correcte receiptbinding aan dezelfde commit, zonder geclaimde exacte tijd uit een readback-upperbound.
6. Bewaar B12 als frozen control: geen wijziging van de verwachting om nieuwe code groen te maken. Nieuwe route krijgt eigen bronset, tests en bewijs.
7. Afzonderlijke beoordeling van contract en bewijs. Alleen bevoegde actor kan acceptatie/release geven.

Status: huidige norm blijft CANONICAL. Onderzoek toegestaan; operationele uitvoering HOLD. Er is nog geen alternatieve storagecandidate gebouwd of gevalideerd.

### Route B — andere deadlinesemantiek voorstellen

Alleen als de opdrachtgever bewust een ander productcontract wil. Bijvoorbeeld: expiry bindt aan een logisch besluit en later duurzaam worden mag onder expliciete voorwaarden. Dit is geen interpretatie van het bestaande D-013: het verandert de gekozen autoriteitsgrens en mogelijk het crash-/revoke-/receiptcontract.

Vereist expliciet nieuw besluit met ten minste: wat precies vóór expiry geldig wordt, waarom dat autoriteit draagt bij crash, welk laat effect wordt toegestaan, intrekkingsvolgorde, bewaarbeleid voor onzekerheid, gebruikersuitleg en nieuwe acceptatiecriteria. Geen automatisch voorstel als D-014 canoniseren; identificatie door de bevoegde besluitroute. Niet geïmplementeerd, niet geautoriseerd door GO of dit dossier.

### Geen geldige shortcut

De bestaande SQLite-route vrijgeven met algemene D-013-conformance terwijl B12 blijft bestaan is geen optie onder de actuele norm. Ook een positieve harnessreview verleent die vrijgave niet.

## Review en besluitgrens

AI-review aan de hand van drie lenzen, uitgevoerd door dezelfde assistent als de bouwer:

- TRIAS: D-013 niet versoepeld. Route B vereist een expliciet nieuw bevoegd besluit. Integratie, productie, merge en PROOF blijven HOLD/niet geautoriseerd.
- ORACLE: primaire bron opnieuw gelezen; B12 getallen herleidbaar; geen exact fsync-tijdstip, andere storagegarantie of onafhankelijke reviewer verzonnen.
- MENTOR: stop het uitbreiden van de harness zonder concrete bevinding. Kies de runtime-/contractroute en maak daarna één afzonderlijke candidate met eigen acceptatiebewijs.

Werkstatus: ANALYSIS COMPLETE / REVIEWABLE DECISION DOSSIER. Verificatie: bestaande lokale B12-evidence gelezen en vergeleken; dit is geen nieuwe runtimerun. Harness-CI blijft aan zijn eigen head gebonden. Formele onafhankelijke acceptatie PENDING.

Volgende geldige overgang: dossier → Route A storageonderzoek onder ongewijzigd D-013, of expliciet opdrachtgeversbesluit voor Route B vóór implementatie van die nieuwe semantiek. Geen tijdsverloop, GO-herhaling of groene CI kiest Route B automatisch.
