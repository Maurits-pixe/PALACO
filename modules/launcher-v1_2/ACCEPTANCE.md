# PALACO Launcher v1.2 — gerichte acceptatiebasis

Afzonderlijke herstelcandidate voor de aangeleverde v1.1. De oorspronkelijke review en brontranscripties blijven intact. Deze basis vertaalt uitsluitend de zichtbare eisen en aangetoonde tegenvoorbeelden; een volledig DRAFT-contract is niet meegeleverd.

1. Alleen exacte, zuivere HTTPS-origins uit de bestaande moduleconfiguratie mogen een request starten. Geen credentials, pad, query, fragment of redirects.
2. Eén poging bezit haar eigen onveranderlijke origin, verwachte appId, controller en monotone deadline. Pogingidentiteit staat los van de wallclock.
3. Na iedere await en vóór acceptatie moet de poging nog eigenaar zijn. Oude catch/finally/timers mogen de opvolger niet wijzigen. Invoerwijziging, annuleren en unmount trekken ownership onmiddellijk in.
4. Request, body, JSON-parsing en type-/identiteitscontrole vallen onder één deadline van 5000 ms. Geen metadataresultaat wordt geaccepteerd op of na deze deadline, ook bij een vertraagde watchdogcallback.
5. JSON-parsing draait in een terminateerbare worker. De geaccepteerde body is maximaal 64 KiB; dit is een expliciete technische begrenzing voor deze candidate. Het leespad stopt zodra die grens wordt overschreden.
6. JavaScript/browserplanning kan een timercallback vertragen. De garantie is deadlineweigering bij acceptatie en een afbreekbare parseworker; geen bewijs van een harde real-time scheduler of beëindiging van alle OS/netwerkactiviteit exact op 5000 ms.
7. Metadata moet een JSON-object zijn met stringvelden appId en status, met de verwachte appId. Geen status-enum of verder schema wordt als bestaand contract verzonnen.
8. Succes geeft maximaal 60000 ms openmogelijkheid, afgemeten aan een private monotone deadline. Een wallclock-deadline kan deze alleen verkorten. De launchhandler weigert zelfstandig bij `now >= deadline`, ongeacht callback/knopkleur.
9. Terugkeer naar de pagina na focus/visibility/BFCache vereist conservatief opnieuw verifiëren. Dit sluit platformverschillen in slaap-/clockgedrag zonder de geldigheidsduur te verlengen.
10. Classificeer fetch-/bodyfouten op fase en eigen code; zoek nooit naar browserfoutteksten. Maak geen claim over een specifieke CORS-, TLS- of redirectoorzaak bij een ondoorzichtige transportfout.
11. De gebruiker kan een lopende check annuleren of de origin bewerken en daarna een nieuwe check starten. De countdown werkt reactief; lokale weergavetijd is geen bevoegdheidsbron.
12. Dev en preview starten alleen met expliciet benoemde, leesbare en parseerbare key/certificaatbestanden. Geen HTTP-fallback; vaste poort 5173 met strictPort. Build vereist geen lokale ontwikkelcertificaten.

Metadata bevestigt uitsluitend de minimale responsevorm en appId vanaf de ingestelde origin. Het bewijst geen authenticatie, autorisatie, appwerking, domeineigendom of gegarandeerde veiligheid. De bestaande tijdelijke launcher en Bastion-ingang worden door dit pakket niet gepubliceerd of vervangen.
