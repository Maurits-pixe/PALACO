# HARA — broninventarisreview · 2026-11-04

Baseline PR #98 head bc6e3a987e31bb3d81e06498e64debd4518da44b. Vergeleken met fe1473ed: main-updates buiten HARA; geen HARA-bronwijziging.

Bevinding SI-01: verify-evidence controleerde alleen sourceHashes uit het aangeleverde manifest. Een nieuw bestand binnen de modulescope kon ontbreken en toch PASS krijgen. De negatieve test 'unlisted module source' faalde aantoonbaar vóór herstel (before.tap behouden).

Herstel: verifier bepaalt zelf de volledige inventaris van modules/hara/hannie-b-d013, plus de vaste workflow en source-manifest.json. De manifestsleutels moeten exact overeenkomen. Ontbrekende modulebron, ontbrekende workflowhash en niet vermelde nieuwe modulebron worden afgewezen; symlinks in de moduleinventaris worden geweigerd. Broninventaris en artifactverificatie blijven consistentiecontroles van lokale bytes, geen authenticiteitsbewijs of officiële PROOF.

Lokale tests Node 24.19.0: 29/29 toolingtests PASS; 20/20 runtimecontrols PASS. Run ee6c89c9-9804-463e-ad93-6f1c7c034b3f, bronset bc7b8b499367efc9187813acab1ac49a0e3519a40528474bf8b6ff1b2e47d75c. Exact-run verifier PASS: 18 bronnen en 19 artifacts. git diff --check PASS. Runtime src en contract niet gewijzigd. Nieuwe CI moet aan de nieuwe head worden gebonden, oude CI is historisch.

AI-review aan de hand van drie lenzen: TRIAS behoudt candidate-scope en HOLD; ORACLE bewaart falende regressie plus nieuwe positieve/negatieve controles, zonder onafhankelijke-reviewclaim; MENTOR verlangt een volledige inventaris in plaats van een door het manifest gekozen subset. Geen dissent dat dit het B12 late-effectrisico oplost.

Status IMPLEMENTED / LOCAL CONTROLS PASS / ACCEPTANCE HOLD / FORMAL INDEPENDENT ACCEPTANCE PENDING. Volgende overgang: nieuwe exacte head → CI op 24.14.1 en 24.19.0 → afzonderlijke review. Geen merge, integratie, productie of PROOF geautoriseerd.
