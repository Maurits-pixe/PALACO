# D-013 — contract en huidige grenzen

## Doel

Een mutatie mag alleen effect krijgen binnen het geldigheidsvenster van een
vertrouwde, server-side gebonden toestemming. Het doel is late writes na het
verlopen van toestemming te voorkomen. Een browserafteller is nooit de
beslissende klok of bron van bevoegdheid.

Dit document beschrijft het ontwerpdoel en de grenzen van de geleverde previews;
het is geen geaccepteerde nieuwe contractspecificatie of bewijs van compliance.

## Vereiste bewijsgrens

Een controle van server-side tijd vóór een SQL-write is noodzakelijk maar
onvoldoende om een tijdige duurzame commit te bewijzen. Na de controle kan
vertraging optreden, ook tijdens flush/commit. Een atomaire transactie voorkomt
gedeeltelijke databasewijzigingen, maar garandeert niet dat het effect vóór
expiry crash-overlevend duurzaam wordt. PostgreSQL `NOW()` meet bovendien
transactiestarttijd, niet het actuele commitmoment.

Een toekomstige implementatie vereist afzonderlijke contractacceptatie en bewijs
voor ten minste:

- binding van een vertrouwde grant aan identiteit, doel, policy en exact voorstel;
- gezaghebbende tijd en een expliciet gedefinieerd geldigheidsvenster;
- atomaire opslag en ticketconsumptie zonder hergebruik voor andere voorstellen;
- opslag die de afgesproken deadline voor het duurzame effect kan afdwingen;
- duurzame receipts en geautoriseerde readback voor retries en verloren antwoorden;
- post-validatie-, crash- en readback-proeven, inclusief vertraging na de tijdcheck.

Een clienttimeout kan ná commit optreden en bewijst geen rollback. Een herhaalde
aanvraag mag geen nieuwe uitvoeringsbevoegdheid uit een oud resultaat afleiden.

## Wat deze checkout doet

De BASTION-interface gebruikt fictieve taken. Bevestigen schrijft niets,
consumeert geen ticket en verandert geen taak. Uitvoeringsingangen blijven
gesloten met `STORAGE_EFFECT_DEADLINE_UNSUPPORTED`; eerdere onzekere resultaten
blijven `RESULT_UNKNOWN`.

De launcher heeft daarnaast een afzonderlijke standalone guard die
prepare/execute-ingangen weigert. Die guard is geen geïntegreerde opslagbackend
en geen D-013-bewijs. `scripts/start-all.sh` start deze guard niet.

Er wordt hier geen Rust AETHER-engine of Node.js/Socket.IO-mutatiebackend
meegeleverd. Een SQLite-transactie of dertigsecondenafteller toevoegen zou de
ontbrekende garanties niet oplossen.

De bronbeoordelingen blijven leidend:

- [BASTION: beoordeling SQLite-backend](../modules/citadel-bastion-preview/D013-REVIEW.md)
- [Launcher: bronoverdracht en grenzen](../modules/launcher-v1_2/HANDOFF.md)

De bestaande default-deny-tests tonen dat de preview geen taken verandert.
Zij bewijzen niet dat een toekomstige opslagservice D-013-conform is.
