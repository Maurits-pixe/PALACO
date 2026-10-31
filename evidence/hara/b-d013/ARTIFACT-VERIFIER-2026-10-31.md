# HARA — expliciete runverificatie · 2026-10-31

Afzonderlijke revisie bovenop PR #98 head ff54b96ed9e526ce5ba7744ce1eb17fc4744c931. Die head heeft HARA-bronset c8956136f1a4da5af46202bd1974ab19c5aae3c4cbdee036f9cd636b3982f1b0 en eigen CI 41207853150 SUCCESS; beide jobs 20 runtime- en 15 toolingcontrols PASS. Wijziging sinds f11c455 betreft alleen zes GO-18-bestanden door main-update. Oude head/CI wordt niet als bewijs voor deze revisie hergebruikt.

Nieuw: tools/verify-evidence.mjs rekent bronset, bronbytes en alle artifacthashes van één expliciet gekozen run opnieuw uit; controleert exacte artifactset, TAP-tellers, run-ID, processtatus, HOLD-grenzen en behoud van B12 late-effecttegenbewijs. Canonical realpaths mogen de opgegeven roots niet verlaten. result.json is een onbeveiligd manifest: deze controle is consistentiecontrole, geen handtekening, authenticiteitsbewijs of officiële PROOF. De verifier vergelijkt met de opgegeven lokale repositorybytes; geen remote-headattestatie.

Runner geeft run_id door via GITHUB_OUTPUT; CI selecteert uitsluitend die run voor verificatie, niet een historische run of nieuwste directory. Historische runs blijven bewaard.

Lokale uitvoering op Node 24.19.0: 26/26 toolingtests (15 bestaande + 11 verifiercontrols) PASS; 20/20 runtimecontrols PASS; run a6c445f1-f34c-4419-b6c4-94ba6e645d75. Bronset c693f2bf21a5d4e18325556bc5a76e2b859a26740c18a36ef88905f9701f2d98. Verifier: 18 bronhashes, 19 artifacthashes PASS. git diff --check PASS. Runtime en contract ongewijzigd. Nieuwe CI wordt afzonderlijk aan de gepubliceerde revisie gebonden.

AI-review aan de hand van drie lenzen: TRIAS behoudt HOLD en authoritygrenzen; ORACLE voegt uitgevoerde consistentiecontrole en negatieve tests toe, zonder authenticiteitsclaim; MENTOR bindt verificatie aan exacte run-ID en maakt sabotage/foutieve selectie zichtbaar. Dit is eigen AI-review, formele onafhankelijke acceptatie PENDING.

Status IMPLEMENTED / LOCAL CONTROLS PASS / ACCEPTANCE HOLD. Volgende overgang: nieuwe exacte head → Node-matrix en verifier in CI → afzonderlijke review. Geen merge, productie, integratie of PROOF.
