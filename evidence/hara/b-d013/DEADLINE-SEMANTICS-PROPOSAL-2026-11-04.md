# HARA / Hannie — voorstel voor gewijzigde deadlinesemantiek

Datum 2026-11-04. Status: PROPOSAL / NIET BESLIST / NIET GEÏMPLEMENTEERD. Opdracht: de opdrachtgever koos expliciet ‘Voorstel voor gewijzigde deadlinesemantiek ontwerpen’. Die keuze autoriseert dit ontwerp, niet de contractwijziging, runtime, merge of release. Geen definitief besluitnummer toegewezen.

## Aanbevolen wijziging in één zin

Laat de vervaltijd van het schrijfakkoord begrenzen wanneer één exact gebonden opdracht binnen de geserialiseerde mutatietransactie definitief wordt gevalideerd; sta uitsluitend voor die opdracht toe dat dezelfde transactie later duurzaam wordt. Noem die validatietijd nooit een tijdig duurzaam TACP-besluit.

Dit is een bewuste versoepeling van D-010 én D-013, geen verduidelijking ervan. De crash-overlevende gezamenlijke commit blijft de enige duurzame overgang voor besluit en effect, maar de grant-expiry bindt in dit voorstel aan de eerdere transactionele validatie. Een rij die na expiry duurzaam wordt, kan daardoor onder het nieuwe contract geldig zijn. Wie ‘na expiry mag er geen nieuw effect meer ontstaan’ nodig heeft, moet dit voorstel afwijzen.

## Aanleiding en bronnen

[D-010 addendum](https://app.notion.com/p/3f029e9a126a81bba1e6dc9c089df8b8) en [D-013](https://app.notion.com/p/8a4f35ebe743499088178364ec04c58d), primaire bronnen opnieuw gelezen. Beide binden nu aan het duurzame beslissingscommit; D-013 wijst een precommit-sample als vervanging expliciet af. Die bronnen blijven canoniek totdat een bevoegde wijziging is vastgesteld.

Lokale B12 en opslagonderzoek in evidence/hara/b-d013/storage-research-2026-11-04 laten zien waarom alleen afbreken of inhoud onthouden de huidige norm niet sluit. Het nieuwe voorstel verklaart oude FAIL-scenario's niet achteraf PASS onder hun oorspronkelijke contract. Nieuwe semantiek krijgt een afzonderlijke candidate en eigen bewijs.

## Begrippen en drie onderscheiden momenten

| Moment | Definitie | Wat het niet bewijst |
| --- | --- | --- |
| validatedAt | Laatste conservatieve tijdobservatie nadat alle schrijfvoorwaarden gecontroleerd zijn, binnen de mutatie-/revoke-serialisatie en vlak vóór COMMIT | Geen duurzame acceptatie; geen exact commitmoment |
| durable commit | Eén crash-overlevende transactie met autorisatiebesluit, agendaeffect, versie, akkoordverbruik, audit en receiptbinding | Geen bewijs dat die commit vóór grant-expiry plaatsvond |
| durableObservedAt | Tijd van geslaagde read-only reconstructie na crash/verloren ACK | Alleen een waargenomen bovengrens; geen exact fsync-tijdstip |

Tijd telt uitsluitend onder een benoemd tijd-/trustprofiel. Lokale monotone elapsed plus wall-clockvloer kan een synthetisch profiel testen; zij is geen geattesteerde ERA-tijd. Een nieuw proces, restore of onbetrouwbare klok verleent geen nieuwe authority.

## Voorgestelde normtekst ter expliciete goedkeuring

1. Een schrijfgrant staat tot zijn expiry nieuwe exacte opdrachten toe voor zover ook het exacte OWNER-akkoord nog geldig is. Gelijkheid aan expiry is te laat: validatedAt moet strikt kleiner zijn dan beide vervaltijden.
2. Deze gewijzigde semantiek geldt alleen voor een nieuwe grant en een nieuw OWNER-akkoord die dit contractprofiel en `finishAfterExpiry: true` expliciet binden. Bestaande grants worden nooit stilzwijgend geconverteerd. De toestemming betreft één requestdigest, actorcontext, kalender, actie, revisie, grantgeneratie en approval-ID; geen wachtrij van ongespecificeerde toekomstige opdrachten.
3. Binnen dezelfde exclusieve ordering als mutatie en revoke worden scope, ACL, context, actuele grantgeneratie/-status, exact akkoord, bronrevisie en beide expiries opnieuw gecontroleerd. Na de laatste tijdvalidatie mag geen nieuwe autorisatie-afhankelijkheid of opdrachtinhoud meer worden veranderd. Geen nieuwe netwerk-/modelcall tussen validatie en COMMIT.
4. Een opdracht die op die validatiegrens geldig is, mag alleen met ongewijzigde binding in dezelfde transactie duurzaam worden nadat expiry verstrijkt. Dat is de expliciet toegestane afwijking van D-010/D-013. In-memory validatie zonder crash-overlevende commit verleent geen historisch effect of succesvol resultaat.
5. Besluit en effect blijven één atomaire commit. Er komt geen stilzwijgende intentqueue, tweede transactie, latere providerdispatch of afzonderlijk duurzaam acceptatiemoment bij.
6. Een duurzaam gecommitte revoke vóór de mutatiecommit blokkeert de mutatie; commit en revoke gebruiken dezelfde sequence/ordering. Een eerder ingediend maar nog niet duurzaam verwerkt intrekkingsverzoek is geen voltooide revoke. Een write die de ordering/lock al bezit kan daardoor nog vóór de revoke duurzaam worden. De UI moet dit onderscheid expliciet tonen.
7. Revoke na de mutatiecommit laat het historische effect staan en blokkeert nieuwe inhoudsvrijgave. Intrekking is geen terugdraaiopdracht. Een correctie/verwijdering vereist een nieuw exact akkoord en eigen authority.
8. Elke nieuwe inhoudsvrijgave vereist actuele leesauthority met eigen scope/generatie/expiry en revokecontrole aan de vrijgavegrens. Een oude schrijfgrant of validatietijd is geen leesrecht. Zonder actuele leesauthority: geen agenda-inhoud, wel uitsluitend toegestane minimale statusmetadata. Geen OWNER-fallback zonder afzonderlijke grondslag.
9. Vóór duurzaamheid geen definitief succes melden. Bij onbekende commit: RESULT_UNKNOWN/HOLD. Na aantoonbare commit wordt uitsluitend die toestand gereconstrueerd, zonder nieuwe write of opnieuw consumeren van het akkoord. Replay van dezelfde operationId maar andere binding wordt afgewezen.
10. Het voorstel garandeert geen maximale duur tussen validatedAt en duurzaamheid. Een opslag-/schedulerstall kan een al gevalideerde opdracht veel later zichtbaar maken. Een applicatietimeout of best-effort annulering maakt een in-flight commit niet aantoonbaar afwezig. Geen automatische cleanup om dit risico te verbergen.
11. Voor andere agenda-acties, externe providers, betalingen, gezinsdeling en D1 geldt dit profiel niet impliciet. Eerste candidate blijft synthetische CREATE_OWN_EVENT; andere scopes vereisen eigen besluit en contract.
12. Oude bewijsrecords, contractversies en beslissingen blijven onveranderd. D-010/D-013 worden alleen voor dit expliciet benoemde profiel opgevolgd door een nieuw bevoegd besluit. Geen algemene claim dat D-013 alsnog gehaald is.

## Voorgestelde grantbinding en receipt

Nieuwe semantiek-ID (voorlopig, geen registratie): `HARA_WRITE_VALIDATION_DEADLINE_DRAFT_1`.

Grant én exact akkoord moeten contractprofiel en `finishAfterExpiry: true` binden; requestdigest omvat de overeenkomstige referenties. Niet één opt-in voor onbeperkt nieuwe opdrachten. Policy mag dit profiel weigeren.

Nieuwe receiptversie, geen stilzwijgende wijziging van bestaande velden:

- `contractProfile`, `receiptVersion`, operationId, request-/context-/snapshotdigest, owner/tenant/session, calendar/event/revision, grantId/generation, approvalId, auditSequence en gebonden expiries.
- `validatedAt` plus benoemd tijd-/trustprofiel en semantiek: PRECOMMIT_VALIDATION_OBSERVATION.
- `durability`: RECONSTRUCTED_COMMIT als alle gekoppelde rijen crash-overlevend zijn gereconstrueerd.
- `durableObservedAt` met READBACK_UPPER_BOUND. `exactDurableAt`: UNKNOWN, tenzij een toekomstige aparte bron dat werkelijk bewijst.
- `observedAfterExpiry`: vergelijking van readback met expiry. Dit betekent niet automatisch dat de commit zelf na expiry was; in B12 is aanvullend native tegenbewijs beschikbaar.
- `deadlineSatisfied`: uitsluitend voor VALIDATION_DEADLINE, nooit DURABLE_COMMIT_DEADLINE. Geen generiek booleaans ‘tijdig’ zonder profiel.

D-010's bestaande decisionAt/effectAt worden niet gevuld met dezelfde precommit-sample. De voorgestelde receiptversie vervangt voor dit profiel de oude tijdvelden; clients moeten nieuwe betekenis expliciet ondersteunen. Oude clients weigeren de onbekende versie. Geen claim van twee duurzame momenten of een bewezen maximaal restinterval.

## Voorgestelde status- en UI-teksten

| Werkelijke toestand | Statusbetekenis | Voorbeeldtekst |
| --- | --- | --- |
| Nog niet duurzaam vastgesteld | Geen succes of gegarandeerde annulering | ‘De uitvoering wordt gecontroleerd. Opnieuw uitvoeren kan een dubbele opdracht veroorzaken.’ |
| Commit gereconstrueerd, actuele leesauthority aanwezig | Historisch effect bevestigd, geen tijdige durabilityclaim | ‘De opdracht is vastgelegd. Je akkoord was geldig bij de laatste controle; de opslag kon later klaar zijn.’ |
| Commit gereconstrueerd, geen actuele leesauthority | Geen payload | ‘Er is een vastgelegde uitkomst. Nieuwe toestemming is nodig om de inhoud te tonen.’ |
| Intrekking ontvangen maar nog niet gecommit | Verzoek is nog geen voltooid revoke | ‘Intrekking wordt verwerkt. Een uitvoering die al in behandeling is kan nog worden vastgelegd.’ |
| Revoke duurzaam bevestigd | Nieuwe uitvoering/vrijgave blokkeren binnen contract | ‘Toestemming ingetrokken. Eerder vastgelegde wijzigingen blijven bestaan.’ |

Voor het OWNER-akkoord verplicht zichtbaar: ‘Deze ene opdracht mag nog worden vastgelegd nadat dit akkoord verloopt, als de laatste controle ervoor geldig was. Daarvoor is geen gegarandeerde maximale vertraging. Intrekken draait een reeds vastgelegde wijziging niet terug.’ Als dit productrisico niet aanvaardbaar is, kan dit profiel niet worden ingeschakeld.

## Acceptatiematrix voor een nieuwe afzonderlijke candidate

SPECIFICATION — onderstaande tests zijn niet als gewijzigde runtime uitgevoerd:

| Control | Scenario | Verwacht onder voorstel |
| --- | --- | --- |
| N01 | Geldige validatie en commit vóór expiry | Eén effect; receipt met nieuw profiel |
| N02 | Lockwacht, validatedAt op/na grant-expiry | DENIED; geen effect/consumption |
| N03 | Approval-expiry vóór grant-expiry | Vroegste deadline geldt |
| N04 | Geldige validatie; WAL-stall over expiry | Eén laat effect mag bestaan; geen duurzame-deadlineclaim; actuele leesauthority afzonderlijk vereist |
| N05 | Crash na validatie maar vóór COMMIT | Geen duurzaam effect of fictief succes; geen blinde retry |
| N06 | Crash/verloren ACK na commit | Exacte reconstructie, geen tweede effect of tweede akkoordverbruik |
| N07 | False ACK vóór commit | Geen succes zonder volledige readback |
| N08 | Revoke duurzaam vóór mutation-ordering | Geen mutatie |
| N09 | Mutatie bezit ordering; revokeverzoek arriveert tijdens stall | Auditsequence bepaalt; geen vroegtijdige UI-bevestiging van revoke |
| N10 | Revoke na commit, vóór inhoudsvrijgave | Historie behouden, payload geweigerd |
| N11 | Leesauthority expired tijdens vrijgavewacht | Payload geweigerd, ook bij geldige historische schrijfvalidatie |
| N12 | Andere digest/context/generation/revisie | Afwijzen; geen binding repareren via replay |
| N13 | Nieuw proces/klokterugloop/restore zonder tijd-trustbewijs | UNKNOWN/HOLD; geen gereconstrueerde authority uit alleen een timestamp |
| N14 | Ontbrekende profielbinding of finishAfterExpiry-opt-in | Nieuwe semantiek niet gebruiken; geen grant-upgrade |
| N15 | Oude client of receiptversie | Nieuwe profielen/velden niet als oude D-013-success verwerken |
| N16 | Interrupt meldt API-fout na toch gecommitte late write | Eerst reconstrueren, geen automatische tweede write of terugdraaiing |

N04 is het bewuste verschil met D-013; het is niet meer dezelfde testverwachting onder dezelfde canon. Historische B12 blijft frozen en blijft bewijs van niet-conformance met D-013. N04 vereist nieuwe fixtures, nieuw profiel en eigen bron-/runbinding.

## Besluit en implementatiegates

De opdrachtgever kan de bovenstaande norm en restrisico expliciet aannemen of afwijzen. Ontwerpgoedkeuring is apart van implementatie-, acceptatie-, integratie- en releasegoedkeuring.

Bij aannemen: bevoegd besluit registreren met exacte versie/digest; D-010/D-013-opvolging en nieuwe receipt-/clientversie binden; daarna één aparte synthetische candidate bouwen. De nieuwe kandidaat erft geen acceptatie of PASS van de oude candidate. Restore-/trust-epoch en betrouwbare tijd blijven expliciete blockers waar vereist.

Bij afwijzen: D-013 ongewijzigd; huidige runtime HOLD; alleen opslagonderzoek met echte deadlinegarantie voortzetten.

Huidige status: DESIGN COMPLETE / NORMTEXT PROPOSED / DECISION PENDING / NEW SEMANTICS NOT IMPLEMENTED / ACCEPTANCE HOLD. Dit ontwerp is geen aanvraag om de huidige PR te mergen.

## AI-review aan de hand van drie lenzen

TRIAS: benoemt expliciet dat zowel D-010 als D-013 moeten wijzigen; geen oude grants, receiptvelden of scopes stilzwijgend herinterpreteren. ORACLE: onderscheidt validatietijd, duurzaamheid en readback; behoudt alle oude tegenbewijs en erkent onbegrensde latency en niet uitgevoerde nieuwe controls. MENTOR: één begrijpelijke opt-in voor één opdracht, heldere intrekkingsuitleg en 16 concrete acceptatiecontrols. Dissent: dit profiel voldoet bewust niet aan de bestaande eis ‘duurzaam vóór expiry’; wie dat nodig heeft moet het afwijzen. Eén AI-bouwer, geen formele onafhankelijke review of officiële PROOF.
