# Review van de aangeleverde SQLite-mutatiebackend

Last Updated: 2026-10-07

De aangeleverde backend wordt niet aangesloten. Zij is een nuttige schets van routes en foutnamen, maar geen D-013-bewijs.

- `db.transaction()` en WAL maken een SQLite-transactie atomair voor de database; zij bewijzen niet dat de besluit-effectcommit vóór de toestemmingsexpiry crash-overlevend duurzaam is.
- `Date.now()` wordt vóór de SQL-write gemeten. Een vertraging na die meting kan alsnog een late duurzame mutatie opleveren. Een check met `clock_timestamp()` of `Date.now()` verplaatst de grens niet naar de commit.
- SQLite ondersteunt de getoonde `SELECT ... FOR UPDATE`-syntaxis niet als PostgreSQL-lockmodel. De voorbeeldcode is daarom niet zonder aanpassing uitvoerbaar.
- `ownerId` komt uit de clientpayload en bindt niet aan een vertrouwde servergrant, kalender, policy of exact voorstel-digest. De voorbereiding verzint bovendien een nieuw venster van dertig seconden.
- Het `UPDATE ... is_consumed` gevolgd door een exception rolt mee terug. Dat is geen duurzame consumption-, receipt- of idempotencybinding voor een verloren antwoord.
- Een succesvolle response of een timeout wordt niet via een geautoriseerde readback gereconstrueerd. Een timeout kan na commit vallen; `NIET doorgevoerd`, rollback en een blinde retry zijn dan onjuist.

Daarom blijft deze preview functioneel gesloten. Alle uitvoeringsingangen geven `STORAGE_EFFECT_DEADLINE_UNSUPPORTED`; een onzekere eerdere poging blijft `RESULT_UNKNOWN`. Pas na een afzonderlijk bevoegd contractbesluit en een gecontroleerde post-validatie/crash/readback-proef kan een echte backend worden ontworpen.
