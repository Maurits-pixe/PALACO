# Nieuwe controles — bronoverdracht 2026-10-07

Last Updated: 2026-10-07

68 verschillende controles PASS, nul testfalen in de hieronder genoemde definitieve runs. Dit bewijst het begrensde launchergedrag en de aparte blokkade, geen D-013-conformiteit of functionerende achterliggende apps.

| Suite | Resultaat | Run |
| --- | --- | --- |
| Controller | 32/32 | `49fe67fb-cfee-45ef-a90a-d5752e3a6702` |
| Vite / TLS | 7/7 | `1c9116aa-689d-460a-911f-54668dd76c56` |
| Browser met lokale HTTPS-fixtures | 21/21 | `42292dd5-9f44-4113-9f9e-990343e4aacf` |
| Aanvullende echte touchscreen-tap | 1/1 | `a699674d-996c-4b17-b328-7ab6086b04c9` |
| Losse HTTP-serverguard / RESULT_UNKNOWN | 7/7 | `evidence/guard-final.tap` |

Totaal: 68 (32 + 7 + 21 + 1 + 7). De browserharness kreeg na de 21/21-run uitsluitend testselectie en een extra taptest; productiebronnen bleven gelijk. Een eerdere controllerrun werd vervangen na wijzigingen aan configuratie en bindingsmanifest.

Native build: Vite 7.3.7, Vue 3.5.43, Playwright 1.62.1, Node 24.21.0 op Windows. Browsertests gebruiken de lokaal geïnstalleerde Microsoft Edge; exacte browserversie staat in het JSON-rapport. Geen globale browserbeveiliging uitgeschakeld. Positieve fixtures accepteren hun tijdelijke CA alleen in de afzonderlijke testcontext; de normale context weigert dezelfde CA.

De echte TTL-proef mat circa 60.183 seconden tot verval; de gecontroleerde tijdproef bevestigt geldig op 59.999 ms en verlopen op 60.000 ms. Klik en tap openen alleen de expliciete lokale fixture; `window.opener` blijft null.

Beveiligingsheaders zijn daadwerkelijk op het antwoord van de lokale gebouwde HTTPS-preview gecontroleerd. `public/_headers` legt dezelfde waarden voor statische hosting vast. Dit is op zichzelf geen bewijs dat de hostingdienst deze headers overneemt; de externe headerstatus wordt apart bij de oplevering gemeld.

Setupgeschiedenis: eerste npm-start vond de runtimewrapper niet; vervolgens is npm met een werkruimtecache gebruikt. Eerste Windows-bouw met gebundelde configloader faalde op padtoegang; native config loading bouwt succesvol. De eerste TLS-start miste de OpenSSL-configuratie en voltooide de suite niet; de wegwerpfixture heeft nu haar eigen configuratie. Dit zijn behouden setupfouten, geen verzwegen groene testruns.

De bewijsmap in het overdrachts-ZIP bevat de ruwe rapporten, bronhashes, logs en screenshots. De oorspronkelijke Linux-bewijsbestanden zijn niet gekopieerd of als lokaal bewijs gepresenteerd.
