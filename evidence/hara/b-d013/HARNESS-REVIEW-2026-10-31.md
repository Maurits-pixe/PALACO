# HARA / Hannie — harnessreview en bewijscontrole · 2026-10-31

Deze revisie volgt op HARNESS-REPAIR-2026-10-31.md; historische runs en verslagen blijven intact.

## Resultaat

Lokale harnesscandidate bovenop 1b2065af0dfe82e25b3f62c80d9f9873563f6afd, nog niet gecommit/gepusht. Nieuwe evidence-checks.mjs weigert PASS tenzij precies 20 controles slagen, fail/cancelled/skipped/todo alle expliciet nul zijn, compile/test/commitlookup zonder fout of signaal eindigen, bronnen ongewijzigd zijn en een 40-hex commitbinding bestaat. Ontbrekende TAP-tellers worden niet meer als nul geïnterpreteerd. sourceCommitAtStart wordt werkelijk vóór de uitvoering opgehaald. CI-configuratie voert de 15 bewijscontroletests afzonderlijk uit. De 20 runtimecontrols en alle src/contractbytes zijn ongewijzigd ten opzichte van HEAD.

## Primaire statuscorrectie

GitHub get_pr_info bevestigt op 31 oktober: PR #38 is merged, merged_at 2026-10-07T03:46:57Z, mergecommit 5ee3b78923da03a41b3f7cfc337289b1edb7f91d, laatste PR-head 1cd0edc0e4c7c77026f784bbd95bae9a76dacf3d. Bron: https://github.com/Maurits-pixe/PALACO/pull/38 . De Notion-/PR-bodybeschrijving met oude head is historisch, geen actuele headbinding. De body behoudt ACCEPTANCE HOLD en formele onafhankelijke acceptatie PENDING. Repositorymerge bewijst geen runtimevrijgave. Geen merge door deze assistent uitgevoerd.

## Uitgevoerde verificatie

- 15/15 bewijscontroletests PASS; inclusief onvolledige selectie, ontbrekende samenvatting/teller, procesfouten bij exit 0, SIGKILL, bronwijziging en ontbrekende commitbinding. TAP in harness-review-2026-10-31/evidence-guards.tap.
- 20/20 crash-/runtimecontrols PASS op Node v24.19.0, Linux, nieuwe run e0c89b20-cd24-4eff-bdac-f3b0594ee333. Geen skips/cancellations/todos. Nieuwe bronset c8956136f1a4da5af46202bd1974ab19c5aae3c4cbdee036f9cd636b3982f1b0, vóór/na gelijk.
- 16 bronhashes en 19 artifacthashes opnieuw berekend: PASS. Native WAL- en SIGKILL-controles uitgevoerd; late-effecttegenbewijs B12 behouden.
- git diff --check PASS; src en CONTRACT.md gelijk aan HEAD.
- Tussenrun eaac55c0-542f-48dc-b8d4-19242b9fb1f6 PASS hoort bij eerdere bronset en vervangt bovenstaande run niet.

## Blokkades en bewijsgrenzen

Node 24.14.1 NOT EXECUTED: installatiepoging via nodejs.org faalt met curl exit 7, proxy:8080 onbereikbaar. Aanwezige extra Node is 24.21.0 en vervangt de afgesproken 24.14.1 niet. Nieuwe GitHub-CI NOT EXECUTED; gewijzigde configuratie staat alleen lokaal. Geen oude CI hergebruikt voor deze revisie. Dit is een eigen AI-review, geen afzonderlijke reviewer of formele onafhankelijke acceptatie.

## AI-review aan de hand van drie lenzen

TRIAS: scope blijft harness/bewijscontrole, geen wijziging van authority of runtimecontract; acceptatie en integratie/productie blijven HOLD. ORACLE: nieuwe hashes/TAP en negatieve controles onderbouwen uitsluitend deze lokale candidate; historische merge correct onderscheiden van acceptatie, ontbrekende matrix/CI expliciet. MENTOR: reviewpatch en binding beschikbaar in harness-review-2026-10-31; next step is dezelfde candidate testen met 24.14.1 zodra de proxy werkt, en daarna publiceren als afzonderlijke review-PR met eigen CI. Geen dissent dat het bekende late effect oplost.

## Overgang

IMPLEMENTED / LOCAL CONTROLS PASS (20 runtime + 15 bewijscontroles) / ACCEPTANCE HOLD. GO voor verdere lokale review binnen scope. Volgende geldige overgang: lokale candidate → complete Node-matrix → afzonderlijke review-PR/CI. Matrix wacht op werkende netwerktoegang of een aanwezige 24.14.1-binary; formele onafhankelijke acceptatie blijft PENDING. Geen productie, integratie, merge of PROOF geautoriseerd door deze controles.
