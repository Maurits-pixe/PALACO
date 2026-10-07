# B D-013 — actuele bronbinding na contractstatuscorrectie

Alleen de statuszin van CONTRACT.md is verduidelijkt: de bouwstatus wordt door afzonderlijke evidence gedragen; het contract verleent geen acceptatie. Geen runtime-, test- of mutatiesemantiek gewijzigd. Oude evidence/CI blijft historische evidence voor de oorspronkelijke head, niet voor deze nieuwe bronset.

Gepubliceerde codecommit 86ab5f8814904d4648394f2e3e95011a6a95b745; geteste lokale codecommit 3f142ab70ad009542a412fb5ee7d263a0676796c. Eigen run 782274e8-fdc1-449d-b109-3206b667fc6d, Node v24.19.0: 15/15 PASS, 0 FAIL/skips/cancelled. Source/artifacthashcheck PASS; bronset vóór/na identiek: b2ae38496d2842d403fd87b5d61299683afb43739aab07863f9090987c634a4e. Scopebytes: revision-2-binding.json. PR #36 blijft 8660ce44; geen R2-uitbreiding, merge, integratie, productie of PROOF.

B12-tegenbewijs blijft intact: native WAL-stall over expiry kan een laat effect achterlaten; geen SUCCEEDED, payload of replay. Metingen zijn readback-upperbounds, geen exacte fsync-tijd of twee durable commits. ACCEPTANCE HOLD / INDEPENDENT REVIEW PENDING. De crash-/revoke-/ACK-controls zijn nieuwe B-evidence; geen deny-PASS hergebruikt.

Vorige B-head af83324e had CI-run 37299555146 SUCCESS: beide Node-jobs 24.14.1 en 24.19.0 rapporteerden 15/15 en bronset e8b9cb9b…; logs gelezen. Nieuwe CI wordt uitsluitend tegen de nieuwe head geregistreerd. De eerdere groene CI is geen bewijs voor de gewijzigde bronset.
