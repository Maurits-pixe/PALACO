# H∆R∆ — BR10 checkout commit binding · 4 november 2026

Bevestigde bevinding: een kopie van de BR09-run met gewijzigd run-ID en sourceCommitAtStart op veertig nullen werd door de oude checker als PASS geaccepteerd. before.json bewaart de daadwerkelijke respons; dit was een negatieve fixture die had moeten falen. Bronhashes waren gelijk. Dit betreft herleidbaarheid van bewijs, geen aangetoonde runtime-authoritydoorbraak.

Herstel: check-evidence.mjs leest Git HEAD via een proces met bestanddescriptor, controleert exit/signal/spawn error en volledige SHA, en vereist exacte gelijkheid met sourceCommitAtStart. Het resultaat rapporteert de gecontroleerde commit. Een historische run van een andere head wordt afgewezen, ook bij identieke scoped sourcebytes. Dit bewijst geen clean working tree of oorsprongsattestatie; actuele bytes blijven afzonderlijk gehasht.

Definitieve lokale run cc4e18da-1259-4cea-982f-9716ce2ffee0: Node v24.19.0/Linux, isolation none, 22/22 runtime PASS; bronset 6e370268b7a19f8d005ba67a4911f7ac674eae94fe7fd6b2836d8334ae92e840 vóór/na gelijk. Checkout tijdens run ee5f62d9099bd3120e2699d0b1c1fe83372d742d met expliciete lokale bronwijzigingen. Checker PASS voor 21 artifacts; acht bewijsprobes PASS, inclusief vervalste commit. verification.json en probes.json bewaren de resultaten.

Remote baseline PR #95 head bcffb4eb8764ef89e00fd6ea6db634b5db0bdabf / base b773ba7f8b02a11fc528f47d9481e92a28015e1d. Vergelijking vanaf BR09-head a54f814 toont alleen andere projectonderdelen, geen Hannie-bron- of workflowwijzigingen. Nieuwe patch wordt bovenop de actuele remote head geplaatst; externe wijzigingen blijven behouden. Nieuwe-head-CI vereist; oudere groene runs zijn geen nieuw-head-bewijs.

AI-review aan de hand van drie lenzen, dezelfde assistent:
- TRIAS: bewijsbinding aangescherpt; geen D-013-, runtime-authority- of opslagsemantiekwijziging.
- ORACLE: vervalsing werkelijk gereproduceerd, daarna 22 runtime- en acht bewijscontroles uitgevoerd. Geen onafhankelijke reviewer of attestation geclaimd.
- MENTOR: concrete SOURCE_COMMIT_MISMATCH en regressie; een nieuwe run is nodig bij een andere checkout, geen hergebruik van historische PASS.

Status IMPLEMENTED / LOCAL CONTROLS PASS / NEW CI PENDING. Onafhankelijke review PENDING; ACCEPTANCE, INTEGRATION, PRODUCTION HOLD wegens bekend B12-late-effecttegenbewijs en open contractacceptatie. Geen merge, deployment, activatie of PROOF. Volgende overgang: exacte nieuwe head naar CI en afzonderlijke review.
