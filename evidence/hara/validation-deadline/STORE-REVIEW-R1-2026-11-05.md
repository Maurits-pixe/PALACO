# HARA — stateful fixture-opslagreview R1

Datum 2026-11-05. Reviewbasis PR #105 head 871c5c47969239af747bdb7ff5fd789b1de9f5be, gestapeld op cf0626fda6841a265e430d91efe29cecdf3821b8. Geen echte admission-, account- of identityservice. Nieuwe reparatie betreft alleen fixturecontrolevelden, regressietests, bewijsverificatie en documentatie; runtimeworker en aangenomen deadlineprofiel blijven gelijk.

## Bevestigde bevinding ST-01

fixtureCall controleerde het canonical databasepad en de vaste synthetische actor. Daarna werd het workerbericht gebouwd als {mode,path,context,request,...extra}. De extra velden konden daardoor de al gecontroleerde besturingsvelden overschrijven. Bij een gewijzigd path werd ook de verkeerde database onder het oorspronkelijke flock-pad geopend. Dit brak de gepubliceerde fixturefence. Geen productie-endpoint of echte gebruikerscredential was betrokken.

I17 gebruikt twee tijdelijke synthetische databases en probeert de worker naar outside.sqlite te sturen. Voor herstel werd daar werkelijk fixture_challenges aangemaakt. I18 probeert context, exact request en mode te overschrijven. Baseline-run 0add406d-7606-40b8-ada4-d3bef7371deb: runtime 24/24, client 13/13 en model 20/20 PASS, fixtureopslag 16/18 PASS / 2 FAIL. I17.json en beide falende TAP-cases zijn behouden. Het ongewenste doel was uitsluitend een tweede wegwerpfixture, geen extern bestand of account.

## Herstel

Extra invoer wordt als gewone canonieke data gevalideerd. mode, path, context en request zijn gereserveerd: aanwezigheid in extra geeft FIXTURE_CONTROL_OVERRIDE vóór spawn. Er is geen mogelijkheid om via die velden de eerder gecheckte binding te vervangen, ook niet met een gelijke waarde. Geldige bestaande helpercalls houden hun gedrag.

De fence is geen sandbox tegen vertrouwde lokale code, environment-injectie voor testfixtures of willekeurige filesystemtoegang; die lagen vielen en vallen buiten dit fixture-threatmodel. Geen echte authenticatiegarantie uit een tijdelijke directorynaam of synthetic-owner afgeleid.

## Nieuwe verificatie

Finale lokale run a0f312a4-6e95-4c1c-8a55-b5eeecbbb15a op Node v24.19.0 Linux: 24/24 runtime + 13/13 client + 20/20 snapshot + 18/18 stateful fixturecontrols PASS; nul fail/skip/cancel/todo. Bronset 849aeda2daf7e4c6af6c768f0f51365f41569dc5b4ea8c3c6e779756afe0ab06 vóór/na gelijk. Verifier PASS: 22 bronnen, 44 artifacts, vier afzonderlijke TAP/exit/countergroepen. I17 targetChallengeTableCreated=false en rejected=true; I18 bevestigt ongewijzigde fixturestaat. Bestaande crash-/native WAL-/concurrency-/replaycontrols blijven groen. git diff --check PASS.

STORE-REVIEW-FAIL-SOURCE-BINDING.json bindt elke bronhash van de falende run aan de reparatie-tree of exact eerder gepubliceerde head 871c5c47969239af747bdb7ff5fd789b1de9f5be. De vorige helper-, contract- en README-bytes zijn van die head opgehaald en met de FAIL-manifesthashes vergeleken. Alle andere FAIL-bronbytes zijn in deze reparatierevisie behouden. REPAIR_TREE in dat record betekent de Git-tree van de commit die dit record introduceert. Geen oude sourceHash stilzwijgend als nieuw bewijs gebruikt.

## Reviewafsluiting en resterende overgang

AI-review aan de hand van drie lenzen: TRIAS bewaart fixture-scope en voorkomt vervanging van al gefencete besturingsvelden; ORACLE bewaart daadwerkelijke ongewenste fixturemutatie plus FAIL/PASS en volledige bronmapping; MENTOR sluit de concrete spread-orderfout zonder productieauthority te suggereren. Dit is eigen AI-review door dezelfde bouwer, geen formeel onafhankelijke acceptatie.

De afgebakende opslagreview is na ST-01-herstel afgerond binnen de onderzochte paden. Nieuwe matrix-CI moet aan de exacte gepubliceerde herstelhead worden gebonden. Echte identity/originverificatie, bevoegd akkoorduitgiftepunt, externe betrouwbare tijd en restore-/trust-epoch blijven niet gebonden of niet gebouwd. De RIO-testscope is daarvoor niet gepromoveerd. Geen browserverbinding, accountintegratie, merge of deployment uitgevoerd.

Status ST-01 LOCALLY RESOLVED / FOUR-SUITE CONTROLS PASS / SCOPED AI-REVIEW COMPLETE / FORMAL INDEPENDENT ACCEPTANCE PENDING / REAL ADMISSION NOT IMPLEMENTED / INTEGRATION HOLD / PRODUCTION HOLD. Volgende geldige overgang: herstelhead → eigen matrix-CI → expliciete echte authority-/tijdbronbinding vóór productadmission. Geen officiële PROOF.
